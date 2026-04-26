import json
from pathlib import Path

listing_path = Path('artifacts/test_sites_acceptance/20260426T023421Z__full_pipeline__test_sites_tail.json')
detail_path = Path('artifacts/test_sites_acceptance/20260426T023815Z__full_pipeline__test_sites_tail.json')

with open(listing_path) as f:
    listing_data = json.load(f)
with open(detail_path) as f:
    detail_data = json.load(f)

print('=== LISTING RESULTS ===')
for r in listing_data['results']:
    print(f"{r['name']}: {r['records']} records, {r['failure_mode']}, {r['quality_verdict']}, {r['elapsed_s']}s")
    
print()
print('=== DETAIL RESULTS ===')
for r in detail_data['results']:
    print(f"{r['name']}: {r['records']} records, {r['failure_mode']}, {r['quality_verdict']}, {r['elapsed_s']}s")
    if r.get('sample_record_data'):
        price = r['sample_record_data'].get('price', 'N/A')
        print(f"  price={price}")
