import asyncio
import time
import json
import httpx
import os
import sys

# Append the backend directory to sys.path so we could potentially import if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REGRESSION_URLS = [
    {"url": "https://web-scraping.dev/products", "schema": "ecommerce_listing", "name": "Listing web-scraping.dev"},
    {"url": "https://books.toscrape.com/catalogue/page-1.html", "schema": "ecommerce_listing", "name": "Listing books.toscrape"},
    {"url": "https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops", "schema": "ecommerce_listing", "name": "Listing webscraper laptops"},
    {"url": "https://sandbox.oxylabs.io/products", "schema": "ecommerce_listing", "name": "Listing oxylabs sandbox"},
    {"url": "https://www.ifixit.com/Parts", "schema": "ecommerce_listing", "name": "Listing ifixit parts"},
    {"url": "https://web-scraping.dev/product/1", "schema": "ecommerce_detail", "name": "Detail web-scraping.dev"},
    {"url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html", "schema": "ecommerce_detail", "name": "Detail books.toscrape"},
    {"url": "https://sandbox.oxylabs.io/products/1", "schema": "ecommerce_detail", "name": "Detail oxylabs sandbox"},
    {"url": "https://scrapingcourse.com/ecommerce/products/chaz-kangeroo-hoodie", "schema": "ecommerce_detail", "name": "Detail scrapingcourse hoodie"},
    {"url": "https://www.ifixit.com/products/iphone-14-battery", "schema": "ecommerce_detail", "name": "Detail ifixit battery"}
]
PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORT}"
SUCCESS_STATUSES = {"completed", "success"}

async def run_single(client: httpx.AsyncClient, target: dict):
    start = time.perf_counter()
    req_body = {
        "url": target["url"],
        "schema_type": target["schema"],
        "max_records": 10,
        "max_depth": 0,
        "use_llm": False
    }
    
    try:
        resp = await client.post(f"{BASE_URL}/api/crawl/sync", json=req_body, timeout=120)
        data = resp.json()
        duration = time.perf_counter() - start
        
        status = data.get("status", "unknown")
        records = data.get("records", [])
        diagnostics = data.get("diagnostics", {})
        
        return {
            "name": target["name"],
            "url": target["url"],
            "status": status,
            "duration": duration,
            "records_count": len(records),
            "records": records,
            "used_browser": diagnostics.get("acquisition_type") == "browser",
            "diagnostics": diagnostics,
            "error": data.get("error_message")
        }
    except Exception as e:
        duration = time.perf_counter() - start
        return {
            "name": target["name"],
            "url": target["url"],
            "status": "failed",
            "duration": duration,
            "error": str(e)
        }

def compute_coverage(records: list) -> float:
    if not records:
        return 0.0
    
    # Calculate coverage of expected fields across all records
    expected_fields = {"title", "price", "url", "image_url", "brand", "description", "category", "sku"}
    total_expected = len(expected_fields) * len(records)
    actual_found = sum(1 for rec in records for k in expected_fields if rec.get(k))
    
    return round(actual_found / total_expected, 2)

async def main():
    print(f"Starting Regression Suite: {len(REGRESSION_URLS)} targets")
    print(f"Ensure backend server is running at {BASE_URL}\n")
    
    results = []
    async with httpx.AsyncClient() as client:
        for idx, target in enumerate(REGRESSION_URLS, 1):
            print(f"[{idx}/{len(REGRESSION_URLS)}] Processing {target['name']}...")
            res = await run_single(client, target)
            res["coverage"] = compute_coverage(res.get("records", []))
            
            status_symbol = "✅" if res["status"] in SUCCESS_STATUSES else "❌"
            browser_used = "🌐 PB" if res.get("used_browser") else "⚡ CC"
            
            print(f"   {status_symbol} {res['status'].upper()} in {res['duration']:.2f}s | Records: {res.get('records_count', 0)} | Coverage: {res['coverage']} | {browser_used}")
            if res.get("error"):
                print(f"   Error: {res['error']}")
            
            results.append(res)

    report_path = f"regression_report_{int(time.time())}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nRegression complete. Report written to {report_path}")
    
    print("\n--- Summary ---")
    total_time = sum(r["duration"] for r in results)
    avg_latency = total_time / len(results)
    avg_coverage = sum(r.get("coverage", 0) for r in results) / len(results)
    browser_exes = sum(1 for r in results if r.get("used_browser"))
    failed_runs = sum(1 for r in results if r["status"] not in SUCCESS_STATUSES)
    
    print(f"Total time:       {total_time:.2f}s")
    print(f"Average latency:  {avg_latency:.2f}s")
    print(f"Average coverage: {avg_coverage:.2f}")
    print(f"Browser fallbacks:{browser_exes}/{len(results)}")
    print(f"Failed runs:      {failed_runs}")

if __name__ == "__main__":
    asyncio.run(main())
