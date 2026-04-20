Based on a forensic review of the variant extraction pipeline, the crawler is missing variants because the extraction logic assumes every website models variants exactly like Shopify, and fails catastrophically when they don't.
There are three major flaws in the codebase preventing variants from being captured correctly.
1. Hardcoded Shopify Assumptions in JS State (The Biggest Flaw)
File: app/services/js_state_mapper.py -> _variant_option_values (Lines ~320-333)
When the crawler finds hydrated state (like __NEXT_DATA__ or __INITIAL_STATE__), it tries to extract the variants. However, look at how it extracts the option values:
code
Python
def _variant_option_values(variant: dict[str, Any], *, option_names: list[str]) -> dict[str, str]:
    # ...
    for index in range(1, 4):
        # ...
        value = variant.get(f"option{index}") # <--- FATAL FLAW
It explicitly looks for keys named option1, option2, and option3. This is exactly how the Shopify API returns variants.
If a site (like Magento, Salesforce Commerce Cloud, or a custom React app) structures its variants logically, like {"id": 123, "color": "Red", "size": "Large"}, this code completely misses the dimensions. Because the option_values dictionary comes back empty, the Cartesian product resolver fails, and the variants are discarded.
The Fix:
You must update _normalize_variant and _variant_option_values to accept explicit dimensional keys (color, size, style, flavor, etc.) if option1 isn't present.
code
Python
def _variant_option_values(variant: dict[str, Any], *, option_names: list[str]) -> dict[str, str]:
    option_values: dict[str, str] = {}
    
    # 1. Try Shopify style first
    raw_options = variant.get("options") if isinstance(variant.get("options"), list) else []
    for index in range(1, 4):
        axis_name = option_names[index - 1] if index - 1 < len(option_names) else f"option_{index}"
        value = variant.get(f"option{index}")
        if value in (None, "", [], {}) and index - 1 < len(raw_options):
            value = raw_options[index - 1]
        
        if value:
            axis_key = normalized_variant_axis_key(axis_name) or f"option_{index}"
            option_values[axis_key] = text_or_none(value)

    # 2. Try Standard Dictionary style (if Shopify style failed)
    if not option_values:
        for possible_axis in ("color", "size", "style", "material", "flavor", "scent", "capacity", "length", "width"):
            val = variant.get(possible_axis)
            if val and isinstance(val, (str, int, float)):
                option_values[possible_axis] = str(val).strip()

    return option_values
2. JSON-LD Hardcodes Only "Color" and "Size"
File: app/services/field_value_candidates.py -> _structured_variant_rows (Lines ~36-68)
When the crawler parses application/ld+json looking for a ProductGroup or Product with a hasVariant array, it maps the dimensions using this code:
code
Python
color = coerce_field_value("color", item.get("color"), page_url)
size = coerce_field_value("size", item.get("size"), page_url)
option_values = {
    key: value
    for key, value in {"color": color, "size": size}.items()  # <--- FLAW
    if value not in (None, "", [], {})
}
If a product has variants based on Material, Style, Weight, or Scent, the JSON-LD parser explicitly drops them. If a variant only differs by a dropped axis, it looks like a duplicate and gets overwritten during deduplication.
The Fix:
You need to inspect the JSON-LD additionalProperty array, which is the standard Schema.org way to define custom variant dimensions.
code
Python
# Update _structured_variant_rows in field_value_candidates.py
option_values = {}
if color: option_values["color"] = color
if size: option_values["size"] = size

# Schema.org additionalProperty extraction
additional_props = item.get("additionalProperty")
if isinstance(additional_props, list):
    for prop in additional_props:
        if isinstance(prop, dict) and prop.get("name") and prop.get("value"):
            axis_key = normalized_variant_axis_key(prop["name"])
            if axis_key:
                option_values[axis_key] = str(prop["value"]).strip()

if option_values:
    row["option_values"] = option_values
3. The DOM Extractor Doesn't Actually Build Variants
File: app/services/detail_extractor.py -> _extract_variants_from_dom (Lines ~388-468)
If a site has no JSON-LD and no Hydrated JS State, the crawler falls back to reading the HTML DOM.
If you look at the return value of _extract_variants_from_dom, it returns:
{"variant_count": 5, "option1_name": "Color", "option1_values": ["Red", "Blue"]}
It only extracts the Axes, not the Variants. It never returns a "variants": [...] array mapping the SKUs/Prices to those colors.
Why? Because doing so strictly from HTML is mathematically impossible without clicking the buttons on the page and observing the price changes. <select> dropdowns don't contain the SKU/Price mapping.
The Fix / Reality Check:
To fix missing variants, you cannot rely on the DOM fallback. You must rely on Fixes 1 & 2 above so that the crawler intercepts the structured data (which does contain the mappings) before it falls back to the DOM.
Make the changes to js_state_mapper.py and field_value_candidates.py and your variant extraction success rate will immediately jump across non-Shopify sites.