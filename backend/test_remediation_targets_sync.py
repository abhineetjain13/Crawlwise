import time
import json
import requests
import sys

PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORT}"

TARGETS = [
    {
        "name": "Reverb",
        "url": "https://reverb.com/marketplace?product_type=electric-guitars",
        "schema": "ecommerce_listing"
    },
    {
        "name": "Musician's Friend",
        "url": "https://www.musiciansfriend.com/snare-drum-heads",
        "schema": "ecommerce_listing"
    },
    {
        "name": "AutoZone",
        "url": "https://www.autozone.com/filters-and-pcv/oil-filter",
        "schema": "ecommerce_listing"
    }
]

def test_target(target):
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
        resp = requests.post(f"{BASE_URL}/api/crawl/sync", json=req_body, timeout=180)
        duration = time.perf_counter() - start
        
        print(f"HTTP Status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"Error Body: {resp.text}")
            return {"name": target["name"], "status": "http_error", "code": resp.status_code}
            
        data = resp.json()
        status = data.get("status", "unknown")
        records = data.get("records", [])
        diagnostics = data.get("diagnostics", {})
        
        print(f"Crawl Status: {status.upper()}")
        print(f"Duration: {duration:.2f}s")
        print(f"Records found: {len(records)}")
        print(f"Acquisition: {diagnostics.get('acquisition_method', 'unknown')}")
        
        if records:
            for i, rec in enumerate(records[:2]):
                print(f"  {i+1}. {rec.get('title')} | {rec.get('price')}")
        
        return {
            "name": target["name"],
            "status": status,
            "duration": duration,
            "records_count": len(records),
            "method": diagnostics.get('acquisition_method', 'unknown')
        }
    except Exception as e:
        print(f"Request Exception: {str(e)}")
        return {"name": target["name"], "status": "exception", "error": str(e)}

def main():
    results = []
    for target in TARGETS:
        res = test_target(target)
        results.append(res)
    
    print("\n=== FINAL SUMMARY ===")
    for res in results:
        symbol = "✅" if res.get("status") in ["completed", "success"] and res.get("records_count", 0) > 0 else "❌"
        print(f"{symbol} {res['name']}: {res.get('records_count', 0)} recs, {res.get('duration', 0):.1f}s, {res.get('method')}")

if __name__ == "__main__":
    main()
