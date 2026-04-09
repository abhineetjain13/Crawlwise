Here are the next 5 critical, copy-pasteable fixes. These resolve Memory Blowouts in React extraction, Watchdog Hangs during timeouts, Browser Crashes from unbounded DOM interaction, Schema Pollution escaping via JSON APIs, and missing Extraction Telemetry.
11. Fix O(N²) Memory Blowout in React State Extraction
File: app/services/extract/listing_extractor.py
Problem: _extract_from_next_flight_scripts concatenates megabytes of JSON chunks into a massive combined string, then searches for substrings inside it while iterating over the chunks. This causes massive memory spikes and CPU lockups on Next.js sites.
Fix: Search for boundaries strictly within the individual chunk, completely eliminating the combined string allocation.
Replace the _extract_from_next_flight_scripts function (around line 557):
code
Python
def _extract_from_next_flight_scripts(html: str, page_url: str) -> list[dict]:
    if "__next_f.push" not in html:
        return []

    decoded_chunks: list[str] = []
    for match in re.finditer(
        r"self\.__next_f\.push\(\[\d+,\s*\"((?:\\.|[^\"\\])*)\"\]\)", html, re.S
    ):
        try:
            decoded = parse_json(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        if decoded:
            decoded_chunks.append(decoded)

    if not decoded_chunks:
        return []

    records_by_url: dict[str, dict] = {}
    pair_patterns = [
        re.compile(
            r'"displayName":"(?P<title>[^"]+)".{0,900}?"listingUrl":"(?P<url>[^"]+)"',
            re.S,
        ),
        re.compile(
            r'"listingUrl":"(?P<url>[^"]+)".{0,900}?"displayName":"(?P<title>[^"]+)"',
            re.S,
        ),
    ]
    brand_pattern = re.compile(r'"name":"(?P<brand>[^"]+)","__typename":"ManufacturerCuratedBrand"')
    sale_price_pattern = re.compile(r'"priceVariation":"(?:SALE|PRIMARY)".{0,220}?"amount":"(?P<amount>[\d.]+)"', re.S)
    original_price_pattern = re.compile(r'"priceVariation":"PREVIOUS".{0,220}?"amount":"(?P<amount>[\d.]+)"', re.S)
    rating_pattern = re.compile(r'"averageRating":(?P<rating>[\d.]+),"totalCount":(?P<count>\d+)')
    availability_pattern = re.compile(r'"(?:shortInventoryStatusMessage|stockStatus)":"(?P<availability>[^"]+)"')

    # FIX: Process exclusively per-chunk. Do not join chunks into a massive string.
    for chunk in decoded_chunks:
        for pair_pattern in pair_patterns:
            for match in pair_pattern.finditer(chunk):
                raw_url = match.group("url")
                title = match.group("title")
                if not title:
                    continue

                # Isolate the search window around the match inside THIS chunk only
                start_index = max(0, match.start() - 1200)
                end_index = min(len(chunk), match.end() + 2200)
                window = chunk[start_index:end_index]
                
                resolved_url = urljoin(page_url, raw_url)
                record = records_by_url.setdefault(
                    resolved_url, {"url": resolved_url, "_source": "next_flight"}
                )
                record["title"] = title

                if brand_match := brand_pattern.search(window):
                    record.setdefault("brand", brand_match.group("brand"))
                if sale_price_match := sale_price_pattern.search(window):
                    record.setdefault("price", sale_price_match.group("amount"))
                if original_price_match := original_price_pattern.search(window):
                    record.setdefault("original_price", original_price_match.group("amount"))
                if rating_match := rating_pattern.search(window):
                    record.setdefault("rating", rating_match.group("rating"))
                    record.setdefault("review_count", rating_match.group("count"))
                if availability_match := availability_pattern.search(window):
                    record.setdefault("availability", availability_match.group("availability"))

    return [
        record
        for record in records_by_url.values()
        if _is_meaningful_listing_record(record, surface="ecommerce_listing")
    ]
12. Prevent Worker Hangs by Unblocking Cancelled Tasks
File: app/services/_batch_runtime.py
Problem: When a URL times out, the watchdog calls await asyncio.gather(*tasks) to wait for cancellation. However, if the task is blocked inside an asyncio.to_thread (like a massive HTML parse), the thread cannot be interrupted. gather will hang forever, breaking the worker.
Fix: Fire-and-forget the cancellation. Let the thread finish and garbage-collect in the background, instantly freeing the event loop.
Replace the _cancel_tasks inner function (around line 231):
code
Python
async def _cancel_tasks(tasks: list[asyncio.Task]) -> None:
            for task in tasks:
                task.cancel()
            
            # FIX: Do NOT await asyncio.gather here. 
            # Tasks running CPU-bound code in asyncio.to_thread cannot be preempted 
            # by cancellation. Awaiting them guarantees the worker hangs indefinitely.
            # Python will garbage collect the task once the background thread completes.
            pass
13. Prevent Browser Crash from Unbounded DOM Interactions
File: app/services/acquisition/browser_client.py
Problem: expand_all_interactive_elements runs a querySelectorAll that can capture thousands of nodes on heavy pages, running .click() on all of them in a tight loop. This crashes the page or triggers anti-bot defenses.
Fix: Impose a hard limit on the number of automated clicks, and wrap them in a safe try/catch.
Replace the Javascript block inside expand_all_interactive_elements (around line 527):
code
Python
async def expand_all_interactive_elements(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object]:
    try:
        # FIX: Added maxClicks limit (20) to prevent browser crashing on heavy DOMs
        expanded_count = await page.evaluate(
            """
            () => {
                let count = 0;
                const maxClicks = 20;
                const seen = new Set();
                const targets = [
                    ...document.querySelectorAll('details > summary'),
                    ...document.querySelectorAll('[aria-expanded="false"]:not([role="menuitem"])'),
                    ...document.querySelectorAll('button[data-toggle]:not([data-toggle="modal"]):not([role="menuitem"])'),
                ].filter((el) => {
                    if (!(el instanceof Element)) return false;
                    if (el.closest('nav, [role="navigation"], [role="menubar"]')) return false;
                    if (el.closest('[aria-modal="true"], [role="dialog"], .modal')) return false;
                    return true;
                });
                for (const el of targets) {
                    if (count >= maxClicks) break;
                    if (!(el instanceof Element) || seen.has(el)) continue;
                    seen.add(el);
                    try {
                        el.click();
                        count++;
                    } catch (error) {}
                }
                return count;
            }
            """,
        )
        if expanded_count:
            logger.debug("Expanded %d interactive elements", expanded_count)
            await _cooperative_sleep_ms(ACCORDION_EXPAND_WAIT_MS, checkpoint=checkpoint)
        return {
            "actions": ["expand_all_interactive_elements"],
            "expanded_count": int(expanded_count or 0),
        }
    except PlaywrightError:
        logger.debug("Interactive element expansion failed (non-critical)", exc_info=True)
    return {}
14. Enforce Strict Validation on JSON APIs (Fix Schema Pollution Route 2)
File: app/services/extract/json_extractor.py
Problem: The DOM pipeline now validates inputs, but the json_extractor.py (which handles direct API responses) bypasses validate_value, allowing garbage strings (like HTML tracking pixels) directly into the database.
Fix: Apply validate_value inside the JSON normalization loop.
Add the import at the top of the file, then update _normalize_item (around line 69):
code
Python
# Add this near the top of json_extractor.py:
from app.services.normalizers import validate_value

# ... further down ...
def _normalize_item(item: dict, page_url: str) -> dict:
    """Map an arbitrary JSON object to canonical fields."""
    record: dict = {}
    consumed_keys: set[str] = set()
    flat = _flatten_one_level(item)
    list_join_fields = {
        "description", "responsibilities", "qualifications", "benefits", "skills",
        "tags", "specifications", "features", "materials", "care", "dimensions",
        "additional_images",
    }

    for canonical, aliases in FIELD_ALIASES.items():
        candidate_keys = [canonical, *aliases]
        values = _find_alias_values(flat, candidate_keys, max_depth=4)
        for value in values:
            normalized = _normalize_json_value(
                canonical,
                value,
                page_url=page_url,
                list_join_fields=list_join_fields,
            )
            if normalized in (None, "", [], {}):
                continue
                
            # FIX: Enforce strict schema validation on JSON API responses 
            # to prevent payload pollution
            validated = validate_value(canonical, normalized)
            if validated in (None, "", [], {}):
                continue
                
            record[canonical] = validated
            consumed_keys.update(key for key in candidate_keys if key in item)
            break

    # ... rest of function remains the same ...
15. Add Missing Extraction Source Telemetry
File: app/services/pipeline/core.py
Problem: When a detail page successfully extracts, the logs say [SAVE] Saved 1 detail records, but it is impossible to know whether the data came from JSON-LD, DOM Selectors, or the LLM fallback. This makes debugging extraction regressions extremely difficult.
Fix: Log the source_trace components so operators know exactly which extraction subsystem is doing the heavy lifting.
Modify the bottom of the _extract_detail function (around line 527):
code
Python
session.add(db_record)
        saved.append(normalized)

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, surface, is_listing=False)
    
    if persist_logs:
        # FIX: Add critical telemetry revealing which extraction layer won arbitration
        winning_sources = []
        if saved:
            for field, val in saved[0].items():
                src_map = source_trace.get("committed_fields", {}).get(field) or \
                          source_trace.get("field_discovery", {}).get(field, {})
                srcs = src_map.get("sources", ["unknown"]) if isinstance(src_map, dict) else ["unknown"]
                winning_sources.append(f"{field}:{srcs[0]}")
                
        source_summary = ", ".join(winning_sources[:5]) + ("..." if len(winning_sources)>5 else "")
        
        await _log(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} detail records (verdict={verdict}). Sources: [{source_summary}]",
        )
        
    await session.flush()
    _finalize_url_metrics(
        url_metrics, records=saved, requested_fields=additional_fields
    )
    return saved, verdict, url_metrics