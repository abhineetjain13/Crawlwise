from app.services.extraction_runtime import extract_records

html = '<html><body><main><h1>Widget Prime</h1><span class="price">$999.99</span></main></body></html>'
records = extract_records(html, 'https://example.com/products/widget-prime', 'ecommerce_detail', max_records=1, requested_fields=['title', 'price'], adapter_records=[{'price': '19.99', '_source': 'adapter'}])
if records:
    print(records[0])
else:
    print("No records extracted")
