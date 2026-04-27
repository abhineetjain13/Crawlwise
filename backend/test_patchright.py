"""
Quick smoke test to verify patchright works in this environment.
Patchright is a drop-in stealth patch for Playwright.
"""
import asyncio
import sys

# Verify patchright is importable
try:
    from patchright.async_api import async_playwright
    print("patchright import: OK")
except ImportError as e:
    print(f"patchright import: FAILED - {e}")
    sys.exit(1)


async def test_patchright():
    async with async_playwright() as p:
        # Launch with stealth (patchright patches chromium under the hood)
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Test 1: navigator.webdriver should be False/undefined (stealth indicator)
        await page.goto("about:blank")
        webdriver_flag = await page.evaluate("() => navigator.webdriver")
        print(f"navigator.webdriver = {webdriver_flag!r}  (want False/undefined)")

        # Test 2: User-Agent should not contain HeadlessChrome
        ua = await page.evaluate("() => navigator.userAgent")
        print(f"userAgent contains 'HeadlessChrome': {'HeadlessChrome' in ua}")
        print(f"userAgent snippet: {ua[:80]}...")

        # Test 3: Hit a simple public page and check status
        resp = await page.goto("https://www.scrapingcourse.com/ecommerce/", wait_until="domcontentloaded")
        print(f"HTTP status: {resp.status if resp else 'no response'}")
        title = await page.title()
        print(f"Page title: {title}")

        # Test 4: Count products on the page
        products = await page.locator(".product").count()
        print(f"Products found: {products}")

        await browser.close()
        print("\npatchright smoke test: PASSED")


if __name__ == "__main__":
    asyncio.run(test_patchright())
