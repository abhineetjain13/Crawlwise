import asyncio
import sys
from bs4 import BeautifulSoup
from app.services.crawl_fetch_runtime import fetch_page
from app.services.config.selectors import CARD_SELECTORS

async def main():
    urls = [
        "https://www.dyson.in",
        "https://www.newbalance.com",
        "https://www.phase-eight.com",
    ]
    for url in urls:
        print(f"\n--- Testing {url} ---")
        try:
            res = await fetch_page(url, prefer_browser=True)
            print(f"Fetched length: {len(res.html or '')}")
            soup = BeautifulSoup(res.html or "", "html.parser")
            found = False
            for sel in CARD_SELECTORS.get("ecommerce", []):
                try:
                    nodes = soup.select(str(sel))
                    if nodes:
                        print(f"Matched {len(nodes)} cards with selector: {sel}")
                        found = True
                except Exception:
                    pass
            if not found:
                print("No card selectors matched!")
                
                # Try to print some common tags to see if we got blocked or empty page
                title = soup.title.string if soup.title else "No Title"
                print(f"Page Title: {title}")
                body_len = len(soup.body.text) if soup.body else 0
                print(f"Body text length: {body_len}")
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
