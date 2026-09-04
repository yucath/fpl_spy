"""
fb_photo_scraper.py — scrape FB Messenger group participant photos.

Run once manually to populate photos/managers/:
    ./venv/bin/python fb_photo_scraper.py

Downloads each participant's avatar to photos/managers/<RealName>.jpg
and writes a mapping.json so the report pipeline can look up photos by
manager (real) name.

Requires: FB_EMAIL, FB_PASSWORD, FB_THREAD_ID in .env
          Chrome/Chromium + chromedriver (same requirement as fb_manager.py)
"""

from __future__ import annotations

import json
import os
import time

import requests
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from fb_manager import FacebookManager

load_dotenv()

LOCAL_DIR   = os.path.dirname(os.path.realpath(__file__))
PHOTOS_DIR  = os.path.join(LOCAL_DIR, "photos", "managers")
MAPPING_FILE = os.path.join(PHOTOS_DIR, "mapping.json")

# FB display name → real name for participants whose FB name differs from FPL name
KNOWN_ALIASES: dict[str, str] = {
    "White Fang": "Sahil Rauniyar",
}


def _real_name(display_name: str) -> str:
    return KNOWN_ALIASES.get(display_name, display_name)


def _download(url: str, dest: str) -> bool:
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"  Download failed: {e}")
    return False


def scrape_group_photos(thread_id: str) -> dict[str, str]:
    """
    Opens the Messenger thread, visits the group info panel, and extracts
    each participant's name + profile photo URL.

    Returns mapping: real_name -> local_file_path
    """
    os.makedirs(PHOTOS_DIR, exist_ok=True)

    mgr = FacebookManager(headless=True)
    driver = mgr.driver

    if not mgr.check_if_logged_in():
        mgr.login_and_save_cookies()

    messenger_url = f"https://www.messenger.com/t/{thread_id}"
    print(f"Navigating to {messenger_url}")
    driver.get(messenger_url)
    wait = WebDriverWait(driver, 20)

    # Wait for chat to load
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="mwThreadlistItem"],' +
                                                                     '[role="main"]')))
    except Exception:
        pass
    time.sleep(3)

    # Click the group info / participants panel (gear icon or header)
    # Try multiple selectors that FB uses for the group members panel
    panel_opened = False
    for selector in [
        '[aria-label="Conversation information"]',
        '[aria-label="Members"]',
        'div[role="button"][aria-label*="info"]',
        'div[role="button"][aria-label*="Info"]',
    ]:
        try:
            btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            btn.click()
            panel_opened = True
            print(f"Opened info panel via: {selector}")
            break
        except Exception:
            continue

    if not panel_opened:
        # Try clicking the group name / header to open info panel
        try:
            header = driver.find_element(By.CSS_SELECTOR, 'div[role="heading"], h1, h2')
            header.click()
            panel_opened = True
            print("Opened info panel via header click")
        except Exception:
            print("WARNING: could not open group info panel — trying to extract visible avatars")

    time.sleep(2)

    # Collect all participant entries: each has an img + nearby text
    mapping: dict[str, str] = {}

    # Strategy 1: member list items in the side panel
    member_items = driver.find_elements(By.CSS_SELECTOR,
        'div[role="listitem"], li[data-testid*="member"], div[data-testid*="participant"]')

    print(f"Found {len(member_items)} list items")

    for item in member_items:
        try:
            imgs = item.find_elements(By.TAG_NAME, "img")
            if not imgs:
                continue
            img = imgs[0]
            photo_url = img.get_attribute("src") or ""
            if not photo_url or "static" in photo_url:
                continue

            # Name: look for aria-label on img, or nearby text node
            name = img.get_attribute("aria-label") or ""
            if not name:
                try:
                    name_el = item.find_element(By.CSS_SELECTOR, "span, div[class]")
                    name = name_el.text.strip()
                except Exception:
                    pass

            if not name:
                continue

            real = _real_name(name)
            dest = os.path.join(PHOTOS_DIR, f"{real}.jpg")
            print(f"  {name} → {real}: downloading …")
            if _download(photo_url, dest):
                mapping[real] = dest
                print(f"    ✓ saved to {dest}")
        except Exception as e:
            print(f"  item error: {e}")

    # Strategy 2: fallback — all avatar images in the thread view
    if len(mapping) < 3:
        print("Falling back to all-avatars strategy …")
        all_imgs = driver.find_elements(By.TAG_NAME, "img")
        for img in all_imgs:
            try:
                label = img.get_attribute("aria-label") or ""
                src = img.get_attribute("src") or ""
                if not label or not src or "static" in src:
                    continue
                # Skip non-profile images
                if "profile_picture" not in src and "safe_image" not in src and "rsrc" in src:
                    continue
                real = _real_name(label)
                if real in mapping:
                    continue
                dest = os.path.join(PHOTOS_DIR, f"{real}.jpg")
                print(f"  {label} → {real}: downloading …")
                if _download(src, dest):
                    mapping[real] = dest
            except Exception:
                continue

    driver.quit()
    return mapping


def main() -> None:
    thread_id = os.getenv("FB_THREAD_ID", "")
    if not thread_id:
        print("ERROR: FB_THREAD_ID not set in .env")
        return

    print(f"Scraping photos for thread {thread_id}")
    mapping = scrape_group_photos(thread_id)

    # Save mapping JSON
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Scraped {len(mapping)} photos.")
    print(f"Mapping saved to {MAPPING_FILE}")
    for name, path in sorted(mapping.items()):
        print(f"  {name}: {path}")


def load_photo_mapping() -> dict[str, str]:
    """Load the cached photo mapping produced by main()."""
    if not os.path.exists(MAPPING_FILE):
        return {}
    with open(MAPPING_FILE, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    main()
