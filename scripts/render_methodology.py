"""Render methodology_diagram.html to PNG using Playwright."""
import subprocess, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
HTML_PATH = SCRIPT_DIR / "methodology_diagram.html"
OUT_PATH = SCRIPT_DIR.parent / "images" / "methodology_diagram.png"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1200}, device_scale_factor=2)
    page.goto(f"file://{HTML_PATH.resolve()}")
    page.wait_for_load_state("networkidle")
    # Screenshot just the body content
    body = page.locator("body")
    body.screenshot(path=str(OUT_PATH))
    browser.close()

print(f"Saved: {OUT_PATH} ({OUT_PATH.stat().st_size // 1024}K)")
