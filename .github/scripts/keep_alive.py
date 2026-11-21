"""
Headless browser keep-alive script for Streamlit Community Cloud.
Navigates to the live deployment, establishes WebSocket communication,
and automatically clicks 'Yes, get this app back up!' if hibernated.
"""
import sys
from playwright.sync_api import sync_playwright

TARGET_URL = "https://fazal-secure-text-to-sql.streamlit.app/"


def main():
    print(f"Connecting to {TARGET_URL} via Playwright Chromium...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(TARGET_URL, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print(f"Navigation warning (proceeding): {e}")

        # Check for hibernation screen and wake up button
        wake_btn = page.locator("button:has-text('Yes, get this app back up!')")
        if wake_btn.count() > 0:
            print("App is asleep! Clicking 'Yes, get this app back up!'...")
            wake_btn.first.click()
            page.wait_for_timeout(20000)
            print("Wakeup triggered, container spinning up.")
        else:
            print("App is already awake. Active WebSocket connection established.")

        # Keep browser session open for 10 seconds to let Streamlit register viewer activity
        page.wait_for_timeout(10000)
        print(f"Page title: {page.title()}")
        browser.close()
        print("Keep-alive session successfully completed.")


if __name__ == "__main__":
    main()
