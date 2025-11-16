# 🎨 Art Downloader Suite  
**Automated Pinterest & Pixiv image downloader (original quality, no official API)**  

A collection of Python tools designed to download and archive artwork from major platforms like **Pinterest** and **Pixiv** — even when official APIs are limited or unavailable.  
The suite uses **Selenium automation**, **smart URL extraction**, and fallback techniques to retrieve **full-resolution images** safely and reliably.

---

## 🚀 Features

### ✔ Pinterest Scraper
- Works **without Pinterest API**
- Uses Selenium to scroll and load all pins on your Saved page
- Extracts `pinimg.com` direct URLs
- Automatically converts preview images to `originals/`
- Downloads **full-resolution** artwork
- Supports large collections (10k+ images)

### ✔ Pixiv Downloader
- Downloads images from Pixiv using session cookies
- Supports novels, images, multi-image posts
- Saves in organized folders

### ✔ Combined Downloader *(coming soon)*
- Unified interface for downloading from multiple sites
- One CLI to rule them all

---

## 📦 Project Structure

ArtDownloader/
│
├── src/
│ ├── pinterest_download_pins.py # Pinterest scraper
│ ├── pixiv_downloader.py # Pixiv scraper
│ └── combined_downloader.py # (future) unified script
│
├── downloads/ # Image output (ignored by git)
├── drivers/ # Browser drivers (ignored by git)
│
├── requirements.txt
├── .gitignore
└── README.md

yaml


---

## 🛠 Requirements

- **Python 3.10+**
- **Microsoft Edge browser**
- Matching **msedgedriver.exe** inside `/drivers/`
- Selenium installed (see below)

---

## 📥 Installation

1. Clone the repository:

```console
git clone https://github.com/<your-name>/ArtDownloader.git
cd ArtDownloader
```

Install dependencies in venv

```console
pip install -r requirements.txt
Download the correct Microsoft Edge WebDriver:
https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/
```

Place the msedgedriver.exe file into: Drivers

ArtDownloader/drivers/
▶ Usage
Pinterest Scraper
Open the script:

```console
python src/pinterest_download_pins.py
Login to Pinterest manually
```

Navigate to your Saved page or any board

Press ENTER in the console

Script automatically scrolls and downloads everything

Images are saved in: You can decide


ArtDownloader/downloads/pinterest/
⚠ Disclaimer
This tool is intended for personal backup and archival of your own saved content.
Do not use it for scraping copyrighted content you do not own.
Respect the terms of service of each platform.

🗺 Roadmap
 Unified combined_downloader.py launcher

 GUI version (PyQt / Tkinter)

 Danbooru / Artstation modules

 Multithreaded downloader

 Auto-update mode (sync new pins only)

 Tag-based sorting

🤝 Contributing
Pull Requests are welcome.
Please open an issue first to discuss major changes.

⭐ Support
If you found this project useful, consider giving it a star ⭐ on GitHub — it helps visibility and motivates development!

