import os
import re
import time
from typing import Set, List

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.common.exceptions import StaleElementReferenceException


# ===================== НАСТРОЙКИ =====================

# Путь к msedgedriver.exe
EDGE_DRIVER_PATH = r"drivers\edgedriver_win64\msedgedriver.exe"

# Папка для скачивания картинок
DOWNLOAD_DIR = r"downloads\pinterest_fast"

# Сколько максимум шагов скролла делать
# Для больших бордов (5k+) можно ставить 300–400
MAX_SCROLLS = 300

# Пауза между скроллами (даём времени Pinterest подгрузить контент)
SCROLL_PAUSE = 1.8

# Сколько раз подряд можно НЕ находить новые картинки, чтобы остановиться
STABLE_ROUNDS = 10

# Таймаут HTTP-запросов
REQUEST_TIMEOUT = 25

# Мусор по ключевым словам (оставляем, но БЕЗ фильтра по размеру)
TRASH_KEYWORDS = [
    "avatars", "profile_images", "favicon", "logo", "static"
]

# =====================================================


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def is_trash_image(url: str) -> bool:
    """
    Фильтруем только очевидный мусор.
    Фильтр по размерам отключили, чтобы не терять нормальные пины.
    """
    if any(k in url for k in TRASH_KEYWORDS):
        return True
    return False


def make_original_url(url: str) -> str:
    """
    Превью вида ../236x/../474x/../736x/ → пробуем заменить на /originals/
    """
    return re.sub(r"/\d+x/", "/originals/", url, count=1)


def collect_image_urls(driver,
                       max_scrolls: int,
                       pause: float,
                       stable_rounds: int) -> List[str]:
    """
    Скроллит ТЕКУЩУЮ страницу (board, saved, home feed)
    и собирает все уникальные pinimg.com URL'ы.
    Останавливается, когда несколько итераций подряд не появляется новых URL.
    """
    urls: Set[str] = set()
    stable = 0

    for i in range(max_scrolls):
        print(f"[SCROLL] {i + 1}/{max_scrolls}")

        # 1) Собираем картинки на текущем экране
        before = len(urls)

        try:
            imgs = driver.find_elements(By.TAG_NAME, "img")
        except Exception:
            imgs = []

        for img in imgs:
            try:
                src = img.get_attribute("src") or ""
                srcset = img.get_attribute("srcset") or ""
            except StaleElementReferenceException:
                continue

            candidate = None

            # Если есть srcset → берём самый большой вариант
            if "pinimg.com" in srcset:
                parts = [p.strip().split(" ")[0] for p in srcset.split(",")]
                big_parts = [p for p in parts if "pinimg.com" in p]
                if big_parts:
                    candidate = big_parts[-1]

            # Если нет srcset, но есть обычный src
            if not candidate and "pinimg.com" in src:
                candidate = src

            if not candidate:
                continue
            if is_trash_image(candidate):
                continue

            urls.add(candidate)

        after = len(urls)
        diff = after - before
        print(f"   Картинок собрано: {after} (+{diff})")

        # 2) Проверяем, есть ли прогресс
        if diff == 0:
            stable += 1
            print(f"   Нет новых URL (stable {stable}/{stable_rounds})")
            if stable >= stable_rounds:
                print("   Похоже, контент перестал подгружаться — выходим из скролла.")
                break
        else:
            stable = 0

        # 3) Плавный скролл вниз — не сразу в самый низ, а примерно на экран
        driver.execute_script("window.scrollBy(0, window.innerHeight * 0.8);")
        time.sleep(pause)

    # Финальный проход на всякий случай (если что-то догрузилось в самом конце)
    print("Делаю финальный проход по странице...")
    try:
        imgs = driver.find_elements(By.TAG_NAME, "img")
    except Exception:
        imgs = []

    before_final = len(urls)
    for img in imgs:
        try:
            src = img.get_attribute("src") or ""
            srcset = img.get_attribute("srcset") or ""
        except StaleElementReferenceException:
            continue

        candidate = None
        if "pinimg.com" in srcset:
            parts = [p.strip().split(" ")[0] for p in srcset.split(",")]
            big_parts = [p for p in parts if "pinimg.com" in p]
            if big_parts:
                candidate = big_parts[-1]
        if not candidate and "pinimg.com" in src:
            candidate = src
        if not candidate:
            continue
        if is_trash_image(candidate):
            continue
        urls.add(candidate)

    after_final = len(urls)
    print(f"   Финальный проход добавил: {after_final - before_final} URL")

    return sorted(urls)


def download_image(url: str, out_dir: str, index: int) -> bool:
    """
    Скачивает одну картинку.
    1) пробует /originals/
    2) если не вышло — качает исходный URL
    """
    ensure_dir(out_dir)

    orig_url = make_original_url(url)

    for attempt, u in enumerate([orig_url, url], start=1):
        try:
            r = requests.get(u, timeout=REQUEST_TIMEOUT, stream=True)
            r.raise_for_status()

            ctype = r.headers.get("Content-Type", "").lower()
            ext = ".jpg"
            if "png" in ctype:
                ext = ".png"
            elif "webp" in ctype:
                ext = ".webp"

            fname = f"pinterest_{index:05d}{ext}"
            path = os.path.join(out_dir, fname)

            if os.path.exists(path):
                print(f"[skip] {fname} уже есть")
                return True

            tmp = path + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1024 * 32):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp, path)
            print(f"[OK] {fname} ({'original' if attempt == 1 else 'fallback'})")
            return True

        except Exception as e:
            print(f"[ERR] попытка {attempt} для {u}: {e}")

    return False


def main():
    ensure_dir(DOWNLOAD_DIR)

    if not os.path.isfile(EDGE_DRIVER_PATH):
        print("❌ Не найден msedgedriver.exe по пути:")
        print("   ", EDGE_DRIVER_PATH)
        print("Убедись, что драйвер лежит в drivers\\edgedriver_win64")
        return

    print("=== Pinterest Fast Downloader (board / home feed) ===\n")

    print("Запускаю браузер Edge через Selenium (новое окно, чистый профиль)...")
    edge_options = webdriver.EdgeOptions()
    edge_options.add_argument("--start-maximized")
    # Если хочешь в фоне — можно включить headless:
    # edge_options.add_argument("--headless=new")

    service = EdgeService(executable_path=EDGE_DRIVER_PATH)
    driver = webdriver.Edge(service=service, options=edge_options)

    try:
        print("Открываю https://www.pinterest.com/ ...")
        driver.get("https://www.pinterest.com/")
        time.sleep(3)

        print("\n🔑 Дальше:")
        print("  1) В окне Edge залогинься в свой Pinterest (если нужно).")
        print("  2) Открой ЛЮБУЮ страницу, с которой хочешь качать:")
        print("     - конкретный board (tactical и т.п.)")
        print("     - вкладку Saved (все сохранённые)")
        print("     - даже home feed — он тоже будет считаться.")
        print("  3) Пролистай чуть вниз, чтобы убедиться, что всё грузится.")
        input("  4) Когда будешь на нужной странице — вернись сюда и нажми Enter...\n")

        print("Начинаю скроллить и собирать URL картинок...")
        urls = collect_image_urls(
            driver,
            MAX_SCROLLS,
            SCROLL_PAUSE,
            STABLE_ROUNDS
        )

        print(f"\nНайдено уникальных картинок (pinimg.com): {len(urls)}")

        if not urls:
            print("❌ Не нашёл ни одной картинки. Скорее всего, Pinterest ещё не подгрузил контент или открыт не тот экран.")
            return

        print("\nНачинаю скачивание...")
        total_ok = 0
        for idx, u in enumerate(urls, 1):
            ok = download_image(u, DOWNLOAD_DIR, idx)
            if ok:
                total_ok += 1

        print("\n==== Готово ====")
        print(f"Всего URL:           {len(urls)}")
        print(f"Файлов скачано:      {total_ok}")
        print("Папка с результатом:", os.path.abspath(DOWNLOAD_DIR))

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
