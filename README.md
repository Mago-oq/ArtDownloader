🎨 Art Downloader Suite

Automated Pinterest & Pixiv image downloader (original quality, no official API)

A collection of Python tools designed to download and archive artwork from major platforms like Pinterest and Pixiv — even when official APIs are limited or unavailable.
This suite uses Selenium automation, smart URL extraction, and fallback techniques to retrieve full-resolution images safely and reliably.

🚀 Features
✔ Pinterest Scraper

Works without the Pinterest API

Uses Selenium to scroll and load all pins from your Saved page

Extracts direct pinimg.com URLs

Converts preview images to original quality

Downloads full-resolution artwork

Supports large collections (10k+ images)

✔ Pixiv Downloader

Downloads images from Pixiv using session cookies

Supports single images, multi-image posts, and novels

Saves artwork in organized folders

✔ Combined Downloader (coming soon)

One unified interface for downloading from multiple sites

One CLI to rule them all

📦 Project Structure
ArtDownloader/
│
├── src/
│   ├── pinterest_download_pins.py      # Pinterest scraper
│   ├── pixiv_downloader.py             # Pixiv scraper
│   └── combined_downloader.py          # (future) unified script
│
├── downloads/                          # Image output (ignored by git)
├── drivers/                            # Browser drivers (ignored by git)
│
├── requirements.txt
├── .gitignore
└── README.md

🛠 Requirements

Python 3.10+

Microsoft Edge browser

Matching msedgedriver.exe inside /drivers/

Selenium installed (see below)

📥 Installation
1. Clone the repository
git clone https://github.com/<your-name>/ArtDownloader.git
cd ArtDownloader

2. Install dependencies
pip install -r requirements.txt

3. Download the correct Microsoft Edge WebDriver

Get it here:
Microsoft Edge WebDriver

Place the msedgedriver.exe file into:

ArtDownloader/drivers/

▶ Usage
Pinterest Scraper

Run the script:

python src/pinterest_download_pins.py


Then:

Login to Pinterest manually

Navigate to your Saved page or any board

Press ENTER in the console

The script will automatically scroll and download all images

Images are saved in:

ArtDownloader/downloads/pinterest/

⚠ Disclaimer

This tool is intended for personal backup and archival of your own content.
Do not use it to scrape copyrighted content you do not own.
Always respect platform terms of service.

🗺 Roadmap

 Unified combined_downloader.py launcher

 GUI version (PyQt / Tkinter)

 Danbooru / ArtStation modules

 Multithreaded downloader

 Auto-update mode (sync new pins only)

 Tag-based file sorting

🤝 Contributing

Pull Requests are welcome.
For major changes, please open an issue first to discuss the proposal.

⭐ Support

If you find this project useful, consider giving it a star ⭐ on GitHub — it helps visibility and motivates continued development!