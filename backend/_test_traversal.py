import asyncio
from app.services.acquisition.browser_runtime import browser_fetch

async def main():
    result = await browser_fetch(
        url="https://webscraper.io/test-sites/e-commerce/scroll/computers/laptops",
        timeout_seconds=30.0,
        surface="ecommerce_listing",
        traversal_mode="scroll",
        max_scrolls=5,
    )
    
    print(f"URL: {result.url}")
    print(f"Status: {result.status_code}")
    print(f"Blocked: {result.blocked}")
    print("Diagnostics:", result.browser_diagnostics)

if __name__ == "__main__":
    asyncio.run(main())
