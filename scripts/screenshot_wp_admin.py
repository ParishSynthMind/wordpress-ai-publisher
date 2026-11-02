"""Screenshots of the local WordPress admin for the README (headless Chromium via Playwright).

Logs in to the LOCAL test site only, with the throwaway admin password that
setup_local_wp.sh generated (.env.local.admin). Usage:
    python scripts/screenshot_wp_admin.py POST_ID
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wp_publisher.cli import load_env_file  # noqa: E402

load_env_file(ROOT / ".env.local")
load_env_file(ROOT / ".env.local.admin")
BASE = os.environ["WP_BASE_URL"]
USER = os.environ["WP_USERNAME"]
PASSWORD = os.environ["WP_LOCAL_ADMIN_PASSWORD"]
post_id = sys.argv[1]
out = ROOT / "media"
out.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page.goto(f"{BASE}/wp-login.php")
    page.fill("#user_login", USER)
    page.fill("#user_pass", PASSWORD)
    page.click("#wp-submit")
    page.wait_for_url("**/wp-admin/**")

    page.goto(f"{BASE}/wp-admin/edit.php?post_status=draft&post_type=post")
    page.screenshot(path=str(out / "wp-admin-drafts-list.png"))

    page.goto(f"{BASE}/wp-admin/post.php?post={post_id}&action=edit")
    page.wait_for_timeout(4000)
    for selector in ('button[aria-label="Close"]', ".components-modal__header button"):
        if page.locator(selector).count():
            page.locator(selector).first.click()
            page.wait_for_timeout(500)
    page.screenshot(path=str(out / "wp-admin-draft-editor.png"))

    page.goto(f"{BASE}/?p={post_id}&preview=true")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out / "draft-preview-top.png"))
    faq = page.locator("h2:has-text('Frequently asked questions')")
    if faq.count():
        faq.first.scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, -80)")
        page.screenshot(path=str(out / "draft-preview-faq.png"))
    html = page.content()
    print("meta description in head:", 'name="description"' in html)
    print("FAQPage JSON-LD in page:", '"@type":"FAQPage"' in html)
    browser.close()
