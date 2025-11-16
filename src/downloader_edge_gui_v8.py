#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pixiv-only downloader (v7.5)
- Скачивает ОРИГИНАЛ (полный размер) для иллюстраций/манги
- Поддерживает ugoira (ZIP через ugoira_meta)
- Получает ПОЛНЫЙ список работ профиля: AJAX + ?p= + «умный» скролл
- «Прогревает» вкладками: открывает /artworks/{id}
- Ретраи/бэкофф, стабильный Referer
"""

import os, re, time, json, threading, subprocess, random
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs, urlencode, urlsplit, urlunsplit

import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Selenium (Edge)
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException

# ===================== CONFIG =====================
EDGE_DRIVER_PATH   = r"D:\Projekts\Script\Downloader\drivers\edgedriver_win64\msedgedriver.exe"
REQUEST_TIMEOUT    = 30
DOWNLOAD_ROOT      = "downloads"
PIXIV_REFERER_ROOT = "https://www.pixiv.net/"
# Настройки стратегий (можно выключать по желанию):
USE_AJAX_ALL         = True   # /ajax/user/{uid}/profile/all
USE_PAGE_PAGINATION  = True   # /users/{uid}/artworks?p=N
USE_SMART_SCROLL     = True   # умный скролл с детекцией стабильности
OPEN_ART_IN_NEW_TAB  = True   # прогрев — открыть /artworks/{id} во вкладке
GRAB_UGOIRA          = True   # качать zip ugoira, если есть
MAX_PAGES_TO_SCAN    = 120    # максимум страниц ?p=N
SCROLL_MAX_ROUNDS    = 80     # максимум итераций скролла
SCROLL_STABLE_ROUNDS = 3      # сколько подряд «без роста», чтобы остановиться
# Ретраи:
MAX_RETRIES          = 5
BASE_BACKOFF_S       = 0.7
# ==================================================

# ----------------- helpers (UI/log) -----------------
def ui_log(w: scrolledtext.ScrolledText, msg: str):
    print(msg)
    try:
        w.configure(state='normal')
        w.insert(tk.END, msg + "\n")
        w.configure(state='disabled')
        w.see(tk.END)
    except Exception:
        pass

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def safe_name(s: str) -> str:
    s = unquote(s or "").strip()
    s = re.sub(r'[\\/:*?"<>|]+', '_', s)
    return (s or "unknown")[:160]

def replace_query_param(url: str, key: str, val: str) -> str:
    sp = urlsplit(url)
    q = parse_qs(sp.query)
    q[key] = [val]
    return urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(q, doseq=True), sp.fragment))

def backoff_sleep(try_index: int):
    # try_index: 0..MAX_RETRIES-1
    time.sleep(BASE_BACKOFF_S * (2 ** try_index) + random.random() * 0.3)

# ----------------- requests session from WebDriver cookies -----------------
def get_session_with_cookies(driver, referer: str | None = None) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "ru,en;q=0.9",
    })
    if referer:
        sess.headers["Referer"] = referer
    # Переносим куки из Edge-профиля (важно для R-18)
    try:
        for c in driver.get_cookies():
            try:
                sess.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
            except Exception:
                pass
    except Exception:
        pass
    return sess

def download_binary(sess: requests.Session, url: str, outpath: str, logw, referer: str | None = None) -> bool:
    ensure_dir(os.path.dirname(outpath))
    # Персональный referer на каждый запрос — для Pixiv обязателен
    headers = {}
    if referer:
        headers["Referer"] = referer

    for i in range(MAX_RETRIES):
        try:
            with sess.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    ui_log(logw, f"[retry] HTTP {r.status_code} → {url}")
                    backoff_sleep(i)
                    continue
                if not r.ok:
                    ui_log(logw, f"[!] HTTP {r.status_code}: {url}")
                    return False
                ctype = r.headers.get("Content-Type", "")
                if ("image" not in ctype) and ("octet-stream" not in ctype) and (not url.lower().endswith(".zip")):
                    ui_log(logw, f"[!] Не похоже на изображение/zip ({ctype}): {url}")
                    return False
                tmp = outpath + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1024 * 32):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp, outpath)
                ui_log(logw, f"[ok] {os.path.basename(outpath)}")
                return True
        except requests.exceptions.ReadTimeout:
            ui_log(logw, f"[timeout] {url} (попытка {i+1}/{MAX_RETRIES})")
            backoff_sleep(i)
        except Exception as e:
            ui_log(logw, f"[fail] {os.path.basename(outpath)} -> {e} (попытка {i+1}/{MAX_RETRIES})")
            backoff_sleep(i)
    return False

# ----------------- Edge preflight & setup -----------------
def _gentle_kill_edge():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True, text=True)
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/IM", "msedgewebview2.exe"], capture_output=True, text=True)
    except Exception:
        pass

def preflight_edge_launch(profile_root: str, profile_name: str, logw):
    # Удаляем DevToolsActivePort и lock'и, чтобы не упал на старте
    prof_dir = Path(profile_root) / profile_name
    for name in ["SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"]:
        for p in [Path(profile_root)/name, prof_dir/name]:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
    # Версию драйвера — в лог
    try:
        drv_ver = subprocess.run([EDGE_DRIVER_PATH, "--version"], capture_output=True, text=True)
        if drv_ver and drv_ver.stdout:
            ui_log(logw, f"[i] msedgedriver: {drv_ver.stdout.strip()}")
    except Exception:
        pass

def find_msedge_binary() -> str | None:
    candidates = [
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge SxS\Application\msedge.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None

def setup_edge_driver(profile_dir: str, headless: bool, profile_name: str, logw):
    preflight_edge_launch(profile_dir, profile_name, logw)

    opts = EdgeOptions()
    edge_bin = find_msedge_binary()
    if edge_bin:
        try:
            opts.binary_location = edge_bin  # type: ignore[attr-defined]
            ui_log(logw, f"[i] msedge.exe: {edge_bin}")
        except Exception:
            pass

    # Флаги для стабильной работы
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--enable-unsafe-swiftshader")  # когда WebGL ругается — включаем софт-рендер
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-features=Translate,RendererCodeIntegrity,AutomationControlled")
    opts.add_argument("--disable-renderer-backgrounding")
    opts.add_argument("--disable-background-timer-throttling")
    opts.add_argument("--remote-allow-origins=*")
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument(f"--profile-directory={profile_name}")
    if headless:
        opts.add_argument("--headless=new")

    # Две попытки старта
    try:
        service = EdgeService(executable_path=EDGE_DRIVER_PATH)
        driver = webdriver.Edge(service=service, options=opts)
        ui_log(logw, f"[+] Edge WebDriver запущен. Profile='{profile_name}'")
        return driver
    except WebDriverException:
        ui_log(logw, "[i] Перезапуск: форс-закрытие Edge и повторная попытка…")
        _gentle_kill_edge()
        preflight_edge_launch(profile_dir, profile_name, logw)
        try:
            service = EdgeService(executable_path=EDGE_DRIVER_PATH)
            driver = webdriver.Edge(service=service, options=opts)
            ui_log(logw, f"[+] Edge WebDriver запущен со второй попытки. Profile='{profile_name}'")
            return driver
        except WebDriverException as e2:
            ui_log(logw, "[ERROR] Edge не стартовал с оригинальным профилем. "
                         "Убедись, что версии Edge и msedgedriver совпадают и Edge полностью закрыт.\n"
                         f"{e2}")
            return None

# ----------------- Pixiv helpers -----------------
def pixiv_user_id_from_url(url: str) -> str | None:
    m = re.search(r"/users/(\d+)", url)
    return m.group(1) if m else None

def pixiv_art_id_from_url(url: str) -> str | None:
    m = re.search(r"/artworks/(\d+)", url)
    return m.group(1) if m else None

def pixiv_fetch_user_all_illust_ids(sess: requests.Session, user_id: str, logw=None) -> list[str]:
    if not USE_AJAX_ALL:
        return []
    api = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all?lang=en"
    headers = {"Referer": f"https://www.pixiv.net/users/{user_id}"}
    ids = set()
    for i in range(MAX_RETRIES):
        try:
            r = sess.get(api, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                if logw: ui_log(logw, f"[retry] profile/all HTTP {r.status_code}")
                backoff_sleep(i)
                continue
            if not r.ok:
                if logw: ui_log(logw, f"[!] profile/all HTTP {r.status_code}")
                return []
            j = r.json()
            body = j.get("body", {})
            for key in ("illusts", "manga"):
                d = body.get(key, {}) or {}
                for k in d.keys():
                    if re.fullmatch(r"\d+", k):
                        ids.add(k)
            break
        except Exception as e:
            if logw: ui_log(logw, f"[warn] profile/all: {e} (попытка {i+1})")
            backoff_sleep(i)
    return sorted(ids, key=lambda x: int(x))

def pixiv_collect_ids_via_pages(driver, user_id: str, logw=None) -> list[str]:
    if not USE_PAGE_PAGINATION:
        return []
    ids = set()
    base = f"https://www.pixiv.net/users/{user_id}/artworks"
    for p in range(1, MAX_PAGES_TO_SCAN + 1):
        url = f"{base}?p={p}"
        try:
            driver.get(url); time.sleep(0.9)
            before = len(ids)
            links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/artworks/"]')
            for a in links:
                href = (a.get_attribute("href") or "").split("?")[0]
                m = re.search(r"/artworks/(\d+)$", href)
                if m:
                    ids.add(m.group(1))
            if logw: ui_log(logw, f"[p={p}] найдено id (суммарно): {len(ids)}")
            if len(ids) == before:
                break
        except Exception as e:
            if logw: ui_log(logw, f"[warn] пагинация p={p}: {e}")
            break
    return sorted(ids, key=lambda x: int(x))

def smart_infinite_scroll(driver, logw=None) -> set[str]:
    if not USE_SMART_SCROLL:
        return set()
    last_h = 0
    last_cnt = 0
    stable = 0
    ids = set()
    for i in range(SCROLL_MAX_ROUNDS):
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.9 + random.random()*0.4)
            h = driver.execute_script("return document.body.scrollHeight;")
            links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/artworks/"]')
            cnt = len(links)
            for a in links:
                href = (a.get_attribute("href") or "").split("?")[0]
                m = re.search(r"/artworks/(\d+)$", href)
                if m:
                    ids.add(m.group(1))
            grew = (h > last_h) or (cnt > last_cnt) or (len(ids) > last_cnt)
            last_h, last_cnt = h, len(ids)
            if not grew:
                stable += 1
            else:
                stable = 0
            if logw:
                ui_log(logw, f"[scroll] ids={len(ids)} height={h} stable={stable}/{SCROLL_STABLE_ROUNDS}")
            if stable >= SCROLL_STABLE_ROUNDS:
                break
        except Exception as e:
            if logw: ui_log(logw, f"[warn] scroll: {e}")
            break
    return ids

def pixiv_ajax_pages(sess: requests.Session, illust_id: str) -> list[str]:
    api = f"https://www.pixiv.net/ajax/illust/{illust_id}/pages?lang=en"
    headers = {"Referer": f"https://www.pixiv.net/artworks/{illust_id}"}
    for i in range(MAX_RETRIES):
        try:
            r = sess.get(api, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                backoff_sleep(i); continue
            if not r.ok:
                return []
            j = r.json()
            body = j.get("body", []) or []
            out = []
            for item in body:
                u = (item.get("urls") or {}).get("original")
                if u:
                    out.append(u)
            return out
        except Exception:
            backoff_sleep(i)
    return []

def pixiv_ajax_single(sess: requests.Session, illust_id: str) -> list[str]:
    api = f"https://www.pixiv.net/ajax/illust/{illust_id}?lang=en"
    headers = {"Referer": f"https://www.pixiv.net/artworks/{illust_id}"}
    for i in range(MAX_RETRIES):
        try:
            r = sess.get(api, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                backoff_sleep(i); continue
            if not r.ok:
                return []
            j = r.json()
            body = j.get("body", {}) or {}
            page_count = int(body.get("pageCount", 1))
            illust_type = int(body.get("illustType", 0))  # 2 = ugoira
            urls = []
            orig = (body.get("urls") or {}).get("original")
            if orig:
                base = re.sub(r"_p0(\.[a-z]+)$", r"_p{page}\1", orig, flags=re.I)
                for p in range(page_count):
                    urls.append(base.replace("{page}", str(p)))
            # Вернём также тип — через маркер
            if illust_type == 2 and GRAB_UGOIRA:
                # добавим маркер, чтобы вызывающий код мог проверить тип
                urls.append("__UGOIRA__")
            return urls
        except Exception:
            backoff_sleep(i)
    return []

def pixiv_ugoira_zip_url(sess: requests.Session, illust_id: str) -> str | None:
    api = f"https://www.pixiv.net/ajax/illust/{illust_id}/ugoira_meta?lang=en"
    headers = {"Referer": f"https://www.pixiv.net/artworks/{illust_id}"}
    for i in range(MAX_RETRIES):
        try:
            r = sess.get(api, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                backoff_sleep(i); continue
            if not r.ok:
                return None
            j = r.json()
            u = (((j.get("body") or {}).get("originalSrc")) or "").strip()
            return u or None
        except Exception:
            backoff_sleep(i)
    return None

# ----------------- Pixiv handlers -----------------
def handle_pixiv_user(driver, sess: requests.Session, user_url: str, out_root: str, logw):
    user_id = pixiv_user_id_from_url(user_url)
    if not user_id:
        ui_log(logw, "[!] Не распознал user_id в URL.")
        return

    ui_log(logw, f"[i] Сбор ID работ пользователя {user_id}…")

    # Источник №1: AJAX profile/all
    ids_ajax = pixiv_fetch_user_all_illust_ids(sess, user_id, logw=logw) if USE_AJAX_ALL else []
    ui_log(logw, f"[i] AJAX /profile/all: {len(ids_ajax)} id")

    # Источник №2: пагинация ?p=N
    ids_pages = pixiv_collect_ids_via_pages(driver, user_id, logw=logw) if USE_PAGE_PAGINATION else []
    ui_log(logw, f"[i] Пагинация ?p=N: {len(ids_pages)} id (накопительно)")

    # Источник №3: «умный» скролл
    ids_scroll = set()
    if USE_SMART_SCROLL:
        driver.get(f"https://www.pixiv.net/users/{user_id}/artworks")
        time.sleep(1.0)
        ids_scroll = smart_infinite_scroll(driver, logw=logw)
        ui_log(logw, f"[i] Скролл: +{len(ids_scroll)} id")

    all_ids = sorted(set(ids_ajax) | set(ids_pages) | set(ids_scroll), key=lambda x: int(x))
    ui_log(logw, f"[i] Итого уникальных работ: {len(all_ids)}")

    user_dir = os.path.join(out_root, "pixiv", user_id)
    ensure_dir(user_dir)

    # Пройдёмся по ID и скачаем оригиналы
    for idx, illust_id in enumerate(all_ids, 1):
        ui_log(logw, f"[{idx}/{len(all_ids)}] illust={illust_id}")

        # Прогрев — открыть /artworks/{id} во вкладке и закрыть
        if OPEN_ART_IN_NEW_TAB:
            try:
                main = driver.current_window_handle
                driver.switch_to.new_window('tab')
                tab = driver.current_window_handle
                driver.get(f"https://www.pixiv.net/artworks/{illust_id}")
                time.sleep(0.6 + random.random()*0.3)
                driver.close()
                driver.switch_to.window(main)
            except Exception as e:
                ui_log(logw, f"[warm] вкладка: {e}")

        # Оригиналы через /pages
        originals = pixiv_ajax_pages(sess, illust_id)
        if not originals:
            originals = pixiv_ajax_single(sess, illust_id)

        # Ugoira: если в списке маркер — скачиваем zip
        if "__UGOIRA__" in originals and GRAB_UGOIRA:
            originals = [u for u in originals if u != "__UGOIRA__"]
            zip_url = pixiv_ugoira_zip_url(sess, illust_id)
            if zip_url:
                out_zip = os.path.join(user_dir, f"{illust_id}.ugoira.zip")
                if not os.path.exists(out_zip):
                    download_binary(sess, zip_url, out_zip, logw, referer=f"https://www.pixiv.net/artworks/{illust_id}")

        if not originals:
            ui_log(logw, f"[!] {illust_id}: оригинальные URL не найдены (нужна авторизация/рейтинг?).")
            continue

        # Фильтруем на всякий
        originals = [u for u in originals if ("i.pximg.net" in u and "/img-original/" in u)]

        for u in originals:
            pm = re.search(r"_p(\d+)\.(jpg|png|jpeg|gif|webp)$", u, re.I)
            page_idx = pm.group(1) if pm else "0"
            ext = pm.group(2) if pm else "jpg"
            fname = f"{illust_id}_p{page_idx}.{ext}"
            outp = os.path.join(user_dir, fname)
            if os.path.exists(outp):
                ui_log(logw, f"[skip] {fname}")
                continue
            download_binary(sess, u, outp, logw, referer=f"https://www.pixiv.net/artworks/{illust_id}")

def handle_pixiv_art(driver, sess: requests.Session, art_url: str, out_root: str, logw):
    illust_id = pixiv_art_id_from_url(art_url)
    if not illust_id:
        ui_log(logw, "[!] Не распознал illust_id в URL.")
        return

    base_dir = os.path.join(out_root, "pixiv")
    ensure_dir(base_dir)

    # Прогрев вкладкой
    if OPEN_ART_IN_NEW_TAB:
        try:
            main = driver.current_window_handle
            driver.switch_to.new_window('tab')
            tab = driver.current_window_handle
            driver.get(f"https://www.pixiv.net/artworks/{illust_id}")
            time.sleep(0.6 + random.random()*0.3)
            driver.close()
            driver.switch_to.window(main)
        except Exception as e:
            ui_log(logw, f"[warm] вкладка: {e}")

    originals = pixiv_ajax_pages(sess, illust_id)
    if not originals:
        originals = pixiv_ajax_single(sess, illust_id)

    # Ugoira?
    if "__UGOIRA__" in originals and GRAB_UGOIRA:
        originals = [u for u in originals if u != "__UGOIRA__"]
        zip_url = pixiv_ugoira_zip_url(sess, illust_id)
        if zip_url:
            out_zip = os.path.join(base_dir, f"{illust_id}.ugoira.zip")
            if not os.path.exists(out_zip):
                download_binary(sess, zip_url, out_zip, logw, referer=f"https://www.pixiv.net/artworks/{illust_id}")

    originals = [u for u in originals if ("i.pximg.net" in u and "/img-original/" in u)]
    if not originals:
        ui_log(logw, "[!] Оригинальные URL не найдены.")
        return

    for u in originals:
        pm = re.search(r"_p(\d+)\.(jpg|png|jpeg|gif|webp)$", u, re.I)
        page_idx = pm.group(1) if pm else "0"
        ext = pm.group(2) if pm else "jpg"
        fname = f"{illust_id}_p{page_idx}.{ext}"
        outp = os.path.join(base_dir, fname)
        if os.path.exists(outp):
            ui_log(logw, f"[skip] {fname}")
            continue
        download_binary(sess, u, outp, logw, referer=f"https://www.pixiv.net/artworks/{illust_id}")

def handle_pixiv(driver, url, out_root, logw):
    sess = get_session_with_cookies(driver, PIXIV_REFERER_ROOT)

    if pixiv_user_id_from_url(url):
        handle_pixiv_user(driver, sess, url, out_root, logw)
        return

    if pixiv_art_id_from_url(url):
        handle_pixiv_art(driver, sess, url, out_root, logw)
        return

    # Если непонятная pixiv-страница — попробуем вытащить /artworks/ со страницы
    driver.get(url); time.sleep(1.0)
    ids = set()
    for a in driver.find_elements(By.CSS_SELECTOR, 'a[href*="/artworks/"]'):
        href = (a.get_attribute("href") or "").split("?")[0]
        m = re.search(r"/artworks/(\d+)$", href)
        if m:
            ids.add(m.group(1))
    if not ids:
        ui_log(logw, "[!] На странице не нашёл работ.")
        return
    # Пройдёмся по найденным id как по артам
    for illust_id in sorted(ids, key=lambda x: int(x)):
        handle_pixiv_art(driver, sess, f"https://www.pixiv.net/artworks/{illust_id}", out_root, logw)

# ----------------- Orchestrator (Pixiv only) -----------------
def process_single_url(driver, url, out_root, logw):
    host = (urlparse(url).hostname or "").lower()
    if "pixiv.net" in host:
        ui_log(logw, "[+] Сайт: pixiv");    handle_pixiv(driver, url, out_root, logw)
    else:
        ui_log(logw, "[!] Это не Pixiv. Этот билд v7.5 сфокусирован только на Pixiv.")

# ===================== GUI =====================
class App(ttk.Frame):
    def __init__(self, root):
        super().__init__(root, padding=10)
        self.grid(sticky="nsew")

        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(6, weight=1)

        self.url_var = tk.StringVar()
        self.profile_root_var = tk.StringVar(value=r"C:\Users\dsmag\AppData\Local\Microsoft\Edge\User Data")
        self.profile_name_var = tk.StringVar(value="Default")
        self.out_var = tk.StringVar(value=DOWNLOAD_ROOT)
        self.headless_var = tk.BooleanVar(value=False)

        ttk.Label(self, text="Pixiv URL:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.url_var).grid(row=1, column=0, sticky="ew")

        ttk.Label(self, text="...или несколько URL (по одному в строке):").grid(row=2, column=0, sticky="w", pady=(6,0))
        self.bulk_box = scrolledtext.ScrolledText(self, height=6)
        self.bulk_box.grid(row=3, column=0, sticky="nsew")

        pr = ttk.Frame(self); pr.grid(row=4, column=0, sticky="ew", pady=(8,0)); pr.columnconfigure(1, weight=1)
        ttk.Label(pr, text="Edge User Data:").grid(row=0, column=0, sticky="w")
        ttk.Entry(pr, textvariable=self.profile_root_var).grid(row=0, column=1, sticky="ew", padx=(6,6))
        ttk.Button(pr, text="Browse", command=self._pick_profile_root).grid(row=0, column=2)

        pd = ttk.Frame(self); pd.grid(row=5, column=0, sticky="ew"); pd.columnconfigure(1, weight=1)
        ttk.Label(pd, text="Profile directory (Default / Profile 1 / ...):").grid(row=0, column=0, sticky="w")
        ttk.Entry(pd, textvariable=self.profile_name_var).grid(row=0, column=1, sticky="ew", padx=(6,6))

        of = ttk.Frame(self); of.grid(row=6, column=0, sticky="ew", pady=(6,0)); of.columnconfigure(1, weight=1)
        ttk.Label(of, text="Output folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(of, textvariable=self.out_var).grid(row=0, column=1, sticky="ew", padx=(6,6))
        ttk.Button(of, text="Browse", command=self._pick_out).grid(row=0, column=2, padx=(0,6))
        ttk.Checkbutton(of, text="Headless", variable=self.headless_var).grid(row=0, column=3, sticky="w")

        ctrl = ttk.Frame(self); ctrl.grid(row=7, column=0, sticky="ew", pady=(8,0))
        ttk.Button(ctrl, text="Start", command=self._start).grid(row=0, column=0, padx=(0,8))
        ttk.Button(ctrl, text="Quit", command=self._quit).grid(row=0, column=1)

        ttk.Label(self, text="Log:").grid(row=8, column=0, sticky="w", pady=(8,0))
        self.log = scrolledtext.ScrolledText(self, height=16, state="disabled")
        self.log.grid(row=9, column=0, sticky="nsew")

    def _pick_profile_root(self):
        p = filedialog.askdirectory(title="Select Edge User Data folder (e.g. C:\\Users\\YOU\\AppData\\Local\\Microsoft\\Edge\\User Data)")
        if p:
            self.profile_root_var.set(p)

    def _pick_out(self):
        p = filedialog.askdirectory(title="Select output folder")
        if p:
            self.out_var.set(p)

    def _start(self):
        urls = []
        single = self.url_var.get().strip()
        bulk = self.bulk_box.get("1.0", tk.END).strip()
        if bulk:
            for line in bulk.splitlines():
                ln = line.strip()
                if ln:
                    urls.append(ln)
        elif single:
            urls = [single]
        else:
            messagebox.showwarning("No URLs", "Введите хотя бы один Pixiv URL.")
            return

        profile_root = self.profile_root_var.get().strip()
        profile_name = self.profile_name_var.get().strip() or "Default"
        if not profile_root:
            messagebox.showwarning("Edge profile", "Укажи путь к Edge User Data.")
            return

        out_root = self.out_var.get().strip() or DOWNLOAD_ROOT
        headless = self.headless_var.get()

        threading.Thread(
            target=self._worker,
            args=(urls, profile_root, profile_name, headless, out_root),
            daemon=True
        ).start()

    def _worker(self, urls, profile_root, profile_name, headless, out_root):
        ui_log(self.log, f"[*] Использую ОРИГИНАЛЬНЫЙ профиль: {profile_root}\\{profile_name}")
        ui_log(self.log, "    Скрипт мягко очистит DevToolsActivePort и запустит WebDriver.")
        driver = setup_edge_driver(profile_root, headless, profile_name, self.log)
        if not driver:
            return
        try:
            ensure_dir(out_root)
            for u in urls:
                ui_log(self.log, f"\n=== {u}")
                try:
                    process_single_url(driver, u, out_root, self.log)
                except Exception as e:
                    ui_log(self.log, f"[ERROR] {u}: {e}")
                time.sleep(0.3)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            ui_log(self.log, "\n[*] Готово.")

    def _quit(self):
        self.master.destroy()

# ----------------- main -----------------
def main():
    root = tk.Tk()
    root.title("Pixiv Original Downloader — v7.5 (AJAX + Pages + SmartScroll + Ugoira)")
    root.geometry("920x760")
    root.minsize(780, 560)
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
