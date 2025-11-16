import os
import re
import time
import requests
from typing import Set

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.common.exceptions import StaleElementReferenceException


# ===== НАСТРОЙКИ =====

# СЮДА вставь ссылку на страницу с ТВОИМИ пинами
# пример: "https://www.pinterest.de/твой_ник/_saved/"
START_URL = "https://www.pinterest.com/YOUR_USERNAME/_saved/"

# сколько раз скроллить страницу (увеличь если пинов много)
MAX_SCROLLS = 80

# пауза между скроллами (секунд)
SCROLL_PAUSE = 2.0

# куда сохранять картинки
DOWNLOAD_DIR = r"D:\Projekts\Script\Downloader\downloads\pinterest"

# ПОЛНЫЙ путь до msedgedriver.exe
EDGE_DRIVER_PATH = r"D:\Projekts\Script\Downloader\drivers\edgedriver_win64\msedgedriver.exe"


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def make_original_url(url: str) -> str:
    """
    Меняем /236x/, /474x/, /736x/ и т.п. на /originals/
    """
    return re.sub(r"/\d+x/", "/originals/", url, count=1)


def collect_image_urls(driver: webdriver.Edge,
                       max_scrolls: int,
                       pause: float) -> Set[str]:
    """
    Скроллит страницу и собирает все уникальные ссылки на картинки с pinimg.com.
    Обрабатывает StaleElementReferenceException.
    """
    urls: Set[str] = set()
    last_height = driver.execute_script("return document.body.scrollHeight")

    for i in range(max_scrolls):
        print(f"[SCROLL] {i + 1}/{max_scrolls}")

        # скролл в самый низ
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)

        # собираем все <img> на текущем состоянии DOM
        imgs = driver.find_elements(By.TAG_NAME, "img")
        for img in imgs:
            try:
                src = img.get_attribute("src") or ""
                srcset = img.get_attribute("srcset") or ""
            except StaleElementReferenceException:
                # элемент уже не существует в DOM (после подгрузки) — просто пропускаем
                continue

            candidate = None

            # если есть srcset — берём из него самую крупную картинку
            if "pinimg.com" in srcset:
                parts = [p.strip().split(" ")[0] for p in srcset.split(",")]
                big_parts = [p for p in parts if "pinimg.com" in p]
                if big_parts:
                    candidate = big_parts[-1]  # как правило, последняя — самая большая

            # иначе просто src
            if not candidate and "pinimg.com" in src:
                candidate = src

            if candidate and "pinimg.com" in candidate:
                urls.add(candidate)

        # проверяем, не перестала ли страница расти (конец)
        try:
            new_height = driver.execute_script("return document.body.scrollHeight")
        except Exception:
            # если вдруг сессия отвалилась/вкладка закрыта
            break

        if new_height == last_height:
            print("Достигнут конец страницы (высота не меняется).")
            break
        last_height = new_height

    return urls


def download_image(url: str, folder: str, idx: int) -> bool:
    """
    Скачивает картинку по URL в указанную папку.
    Имя файла: pin_<номер>.(jpg/png/webp)
    """
    orig_url = make_original_url(url)

    for attempt, u in enumerate([orig_url, url], start=1):
        try:
            r = requests.get(u, timeout=20)
            r.raise_for_status()

            # определяем расширение по Content-Type
            ext = ".jpg"
            ct = r.headers.get("Content-Type", "").lower()
            if "png" in ct:
                ext = ".png"
            elif "webp" in ct:
                ext = ".webp"

            filename = os.path.join(folder, f"pin_{idx}{ext}")
            with open(filename, "wb") as f:
                f.write(r.content)

            print(f"[OK] {filename} ({'original' if attempt == 1 else 'fallback'})")
            return True
        except Exception as e:
            print(f"[ERR] попытка {attempt} для {u}: {e}")

    return False


# ===== ОСНОВНАЯ ЛОГИКА =====

def main():
    if "DEIN_USERNAME" in START_URL:
        print("❌ Пожалуйста, вставь реальный URL в переменную START_URL.")
        return

    # проверяем, что именно ФАЙЛ, а не папка
    if not os.path.isfile(EDGE_DRIVER_PATH):
        print(f"❌ EDGE_DRIVER_PATH указывает не на файл.")
        print(f"Текущее значение: {EDGE_DRIVER_PATH}")
        print("Укажи полный путь до msedgedriver.exe, например:")
        print(r'EDGE_DRIVER_PATH = r"D:\Projekts\Script\Downloader\drivers\edgedriver_win64\msedgedriver.exe"')
        return

    ensure_dir(DOWNLOAD_DIR)

    print("Запускаю браузер Edge через Selenium...")
    edge_options = webdriver.EdgeOptions()
    # если хочешь без окна, можно раскомментировать:
    # edge_options.add_argument("--headless=new")

    service = EdgeService(executable_path=EDGE_DRIVER_PATH)
    driver = webdriver.Edge(service=service, options=edge_options)

    try:
        print("Открываю Pinterest...")
        driver.get(START_URL)

        print("\n🔑 Залогинься в Pinterest (если ещё не залогинен).")
        print("Убедись, что открыт экран с твоими сохранёнными пинами или нужной доской.")
        input("Когда будешь на нужной странице и всё загрузится — нажми Enter в этой консоли...\n")

        print("Начинаю скроллить и собирать ссылки на картинки...")
        urls = collect_image_urls(driver, MAX_SCROLLS, SCROLL_PAUSE)
        print(f"\nНайдено уникальных URL картинок: {len(urls)}")

    finally:
        driver.quit()

    if not urls:
        print("❌ Не удалось найти ни одной картинки. Возможно, другая разметка страницы.")
        return

    print("\nНачинаю скачивание...")
    count = 0
    for i, url in enumerate(sorted(urls)):
        ok = download_image(url, DOWNLOAD_DIR, i + 1)
        if ok:
            count += 1

    print("\nГотово.")
    print(f"Всего URL: {len(urls)}")
    print(f"Успешно скачано: {count}")
    print("Папка:", os.path.abspath(DOWNLOAD_DIR))


if __name__ == "__main__":
    main()
