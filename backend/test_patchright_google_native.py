"""
Test whether patchright can replace real_chrome for google-native product-intelligence discovery.

Mirrors the _google_native_session() flow in discovery.py but swaps in patchright,
using the actual internal behavior-mimicry system.
"""
import asyncio
import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

# Ensure backend app imports resolve
sys.path.insert(0, str(Path(__file__).parent))

from bs4 import BeautifulSoup
from patchright.async_api import async_playwright

from app.services.acquisition.browser_recovery import (
    emit_browser_behavior_activity,
    type_text_like_human,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Constants mirrored from app/services/config/product_intelligence.py
GOOGLE_NATIVE_HOME_URL = "https://www.google.com/"
GOOGLE_NATIVE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_NATIVE_QUERY_PARAM = "q"
GOOGLE_NATIVE_RESULT_COUNT_PARAM = "num"
GOOGLE_NATIVE_RESULT_LINK_SELECTOR = "a[href]"
GOOGLE_NATIVE_TITLE_SELECTOR = "h3"
GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH = 6
GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH = 20
GOOGLE_NATIVE_REDIRECT_PATH = "/url"
GOOGLE_NATIVE_REDIRECT_TARGET_PARAM = "q"
GOOGLE_NATIVE_IGNORED_DOMAINS = ("google.com", "webcache.googleusercontent.com")
GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS = 20000
GOOGLE_NATIVE_RESULT_WAIT_MS = 2500


# ---------------------------------------------------------------------------
# Helpers (copied from discovery.py)
# ---------------------------------------------------------------------------
def _clean_result_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"}:
        return ""
    return text


def _domain_matches(domain: str, pattern: str) -> bool:
    pattern = pattern.lower().strip().removeprefix("www.").removesuffix("/")
    domain = domain.lower().strip().removeprefix("www.").removesuffix("/")
    return domain == pattern or domain.endswith(f".{pattern}")


def _google_native_result_url(href: str) -> str:
    raw = str(href or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc.endswith("google.com") and parsed.path == GOOGLE_NATIVE_REDIRECT_PATH:
            target = parse_qs(parsed.query).get(GOOGLE_NATIVE_REDIRECT_TARGET_PARAM, [""])[0]
            return _clean_result_url(target)
        return _clean_result_url(raw)
    if raw.startswith(GOOGLE_NATIVE_REDIRECT_PATH):
        target = parse_qs(urlsplit(raw).query).get(GOOGLE_NATIVE_REDIRECT_TARGET_PARAM, [""])[0]
        return _clean_result_url(target)
    if raw.startswith("/"):
        return _clean_result_url(urljoin(GOOGLE_NATIVE_HOME_URL, raw))
    return ""


def _google_native_anchor_title(anchor) -> str:
    heading = anchor.select_one(GOOGLE_NATIVE_TITLE_SELECTOR)
    if heading is None:
        return ""
    return heading.get_text(" ", strip=True)


def _google_native_anchor_thumbnail(anchor) -> str:
    parent = anchor
    for _ in range(int(GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH)):
        parent = getattr(parent, "parent", None)
        if parent is None:
            break
        for img in parent.find_all("img"):
            src = str(img.get("src") or img.get("data-src") or "").strip()
            if len(src) >= int(GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH):
                return src
    return ""


def _parse_google_native_results(html: str, *, limit: int) -> list[dict]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    results: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.select(GOOGLE_NATIVE_RESULT_LINK_SELECTOR):
        href = str(anchor.get("href") or "").strip()
        url = _google_native_result_url(href)
        if not url or url in seen:
            continue
        domain = urlsplit(url).netloc.removeprefix("www.").lower()
        if any(_domain_matches(domain, item) for item in GOOGLE_NATIVE_IGNORED_DOMAINS):
            continue
        title = _google_native_anchor_title(anchor)
        if not title:
            continue
        thumbnail = _google_native_anchor_thumbnail(anchor)
        seen.add(url)
        results.append({
            "url": url,
            "domain": domain,
            "title": title,
            "thumbnail": thumbnail,
            "position": len(results) + 1,
        })
        if len(results) >= max(1, int(limit)):
            break
    return results


def _google_native_search_url(query: str, limit: int) -> str:
    return (
        f"{GOOGLE_NATIVE_SEARCH_URL}?"
        f"{urlencode({GOOGLE_NATIVE_QUERY_PARAM: query, GOOGLE_NATIVE_RESULT_COUNT_PARAM: str(limit)})}"
    )


# ---------------------------------------------------------------------------
# Patchright test runner
# ---------------------------------------------------------------------------
async def run_patchright_google_native(query: str, limit: int = 10):
    logger.info("Launching patchright browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 1. Go to google.com (WARM-UP PHASE)
        logger.info("[WARM-UP] Navigating to %s", GOOGLE_NATIVE_HOME_URL)
        try:
            await page.goto(
                GOOGLE_NATIVE_HOME_URL,
                wait_until="domcontentloaded",
                timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
            )
        except Exception as exc:
            logger.error("Failed to load Google homepage: %s", exc)
            await browser.close()
            return

        # 2. Quick bot-detection probe
        webdriver_flag = await page.evaluate("() => navigator.webdriver")
        ua = await page.evaluate("() => navigator.userAgent")
        logger.info("navigator.webdriver = %r", webdriver_flag)
        logger.info("User-Agent snippet: %s...", ua[:90])

        # 3. Run production behavior mimicry on google.com before searching
        logger.info("[WARM-UP] Running emit_browser_behavior_activity...")
        behavior_diag = await emit_browser_behavior_activity(page)
        logger.info("[WARM-UP] behavior_diagnostics: %s", behavior_diag)

        # 3b. Type like human into the search box
        logger.info("[WARM-UP] Typing query via type_text_like_human...")
        type_diag = await type_text_like_human(page, "textarea[name='q'], input[name='q']", query)
        logger.info("[WARM-UP] type_diagnostics: %s", type_diag)

        # 3c. Submit and wait
        if type_diag.get("typed_chars", 0) > 0:
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2000)
            await page.wait_for_timeout(int(GOOGLE_NATIVE_RESULT_WAIT_MS))
            logger.info("[WARM-UP] Submitted search via human typing")
        else:
            logger.warning("[WARM-UP] type_text_like_human typed 0 chars — falling back to direct goto")
            search_url = _google_native_search_url(query, limit)
            logger.info("Query URL: %s", search_url)
            try:
                await page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
                )
                await page.wait_for_timeout(int(GOOGLE_NATIVE_RESULT_WAIT_MS))
            except Exception as exc2:
                logger.error("Query navigation failed: %s", exc2)
                await browser.close()
                return

        # 4. Check for obvious block / CAPTCHA indicators
        title = await page.title()
        url = page.url
        logger.info("Page title: %r", title)
        logger.info("Final URL: %s", url)

        if "unusual traffic" in title.lower() or "captcha" in title.lower():
            logger.warning("Possible Google block detected!")

        html = await page.content()
        await browser.close()

        # 4b. Diagnostics — save raw HTML and show a snippet
        snapshot_path = r"C:\Projects\pre_poc_ai_crawler\backend\test_patchright_snapshot.html"
        with open(snapshot_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Saved raw HTML snapshot -> %s", snapshot_path)
        body_snippet = BeautifulSoup(html, "html.parser").body
        snippet = str(body_snippet)[:1200] if body_snippet else html[:1200]
        logger.info("BODY snippet:\n%s", snippet)

        # 5. Parse results with the same extractor as discovery.py
        results = _parse_google_native_results(html, limit=limit)
        logger.info("Extracted %d organic results", len(results))
        for r in results:
            logger.info("  #%(position)d %(domain)s - %(title)s", r)
        return results


if __name__ == "__main__":
    # A realistic product-intelligence query (title + buy intent)
    TEST_QUERY = "Nike Air Force 1 buy"
    results = asyncio.run(run_patchright_google_native(TEST_QUERY, limit=10))
    if results:
        print(f"\nSUCCESS — patchright extracted {len(results)} results for query: {TEST_QUERY!r}")
    else:
        print(f"\nFAILED — patchright returned zero results for query: {TEST_QUERY!r}")
