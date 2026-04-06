import asyncio
import time
import json
import httpx
import sys
import os

PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORT}"

TARGETS = [
    {
        "name": "Reverb",
        "url": "https://reverb.com/marketplace?product_type=electric-guitars",
        "schema": "ecommerce_listing",
        "expected_quality": "High Filter" 
    },
    {
        "name": "Musician's Friend",
        "url": "https://www.musiciansfriend.com/snare-drum-heads",
        "schema": "ecommerce_listing",
        "expected_quality": "High Identification"
    },
    {
        "name": "AutoZone",
        "url": "https://www.autozone.com/filters-and-pcv/oil-filter",
        "schema": "ecommerce_listing",
        "expected_quality": "Fast Escalation"
    }
]

async def test_target(client: httpx.AsyncClient, target: dict):
    print(f"\n--- Testing {target['name']} ---")
    print(f"URL: {target['url']}")
    
    start = time.perf_counter()
    req_body = {
        "url": target["url"],
        "schema_type": target["schema"],
        "max_records": 10,
        "use_llm": False
    }
    
    try:
        # Use sync crawl endpoint
        resp = await client.post(f"{BASE_URL}/api/crawl/sync", json=req_body, timeout=120)
        data = resp.json()
        duration = time.perf_counter() - start
        
        status = data.get("status", "unknown")
        records = data.get("records", [])
        diagnostics = data.get("diagnostics", {})
        acquisition_method = diagnostics.get("acquisition_method", diagnostics.get("method", "unknown"))
        browser_attempted = diagnostics.get("browser_attempted", False)
        
        print(f"Status: {status.upper()}")
        print(f"Duration: {duration:.2f}s")
        print(f"Records found: {len(records)}")
        print(f"Acquisition: {acquisition_method} (Browser: {browser_attempted})")
        
        if records:
            print("\nSample Records:")
            for i, rec in enumerate(records[:3]):
                print(f"  {i+1}. {rec.get('title')} | Price: {rec.get('price')} | Brand: {rec.get('brand')}")
            
            # Check for common noise patterns in titles
            noise_titles = [r.get("title", "").lower() for r in records if any(n in r.get("title", "").lower() for n in ["home", "login", "feedback", "view more"])]
            if noise_titles:
                print(f"  ⚠️ WARNING: Found potential noise in titles: {noise_titles}")
            else:
                print("  ✅ NOISE FILTERING: Passed (no obvious navigation noise in titles)")
        else:
            print("  ❌ ERROR: No records found!")
            if data.get("error_message"):
                print(f"  Error Detail: {data.get('error_message')}")
                
        return {
            "name": target["name"],
            "status": status,
            "duration": duration,
            "records_count": len(records),
            "acquisition": acquisition_method,
            "diagnostics": diagnostics
        }
    except Exception as e:
        print(f"  ❌ REQUEST FAILED: {str(e)}")
        return {"name": target["name"], "status": "failed", "error": str(e)}

async def main():
    async with httpx.AsyncClient() as client:
        results = []
        for target in TARGETS:
            res = await test_target(client, target)
            results.append(res)
        
    print("\n\n=== FINAL SUMMARY ===")
    for res in results:
        status_symbol = "✅" if res.get("status") in ["completed", "success"] and res.get("records_count", 0) > 0 else "❌"
        print(f"{status_symbol} {res['name']}: {res.get('records_count', 0)} records in {res.get('duration', 0):.2f}s ({res.get('acquisition')})")

if __name__ == "__main__":
    asyncio.run(main())
