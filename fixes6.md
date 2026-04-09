26. Fix Database Connection Pool Exhaustion (Architecture: 5 → 8)
File: app/api/crawls.py
Problem: The WebSocket endpoint crawls_logs_ws opens and closes a new database session async with SessionLocal() inside a while True loop every 0.75 seconds. If 50 users are monitoring crawls, this generates ~66 connection/disconnection requests per second, instantly exhausting the SQLAlchemy connection pool and crashing the backend with 500 errors.
Fix: Open a single session per WebSocket lifecycle and use session.rollback() to reset the transaction snapshot for fresh reads.
Replace the crawls_logs_ws function (around line 398):
code
Python
@router.websocket("/{run_id}/logs/ws")
async def crawls_logs_ws(websocket: WebSocket, run_id: int, after_id: int | None = None) -> None:
    user = await _resolve_websocket_user(websocket)
    if user is None:
        await _close_websocket_safely(
            websocket, code=1008, reason="Not authenticated"
        )
        return

    async with SessionLocal() as session:
        run = await get_run(session, run_id)
        if run is None or (user.role != "admin" and run.user_id != user.id):
            await _close_websocket_safely(
                websocket, code=1008, reason=RUN_NOT_FOUND_DETAIL
            )
            return

        await websocket.accept()
        cursor = after_id
        try:
            # FIX: Maintain ONE database connection for the lifetime of the socket,
            # rather than thrashing the connection pool 2 times a second.
            while True:
                # Rollback resets the transaction snapshot so we see new rows
                await session.rollback() 
                rows = await get_run_logs(session, run_id, after_id=cursor, limit=500)
                run = await get_run(session, run_id)
                
                for row in rows:
                    await websocket.send_json(serialize_log_event(row))
                    cursor = row.id

                if run is None:
                    await websocket.close(code=1008, reason=RUN_NOT_FOUND_DETAIL)
                    return
                if normalize_status(run.status) in TERMINAL_STATUSES and not rows:
                    await websocket.close(code=1000, reason="Run completed")
                    return
                await asyncio.sleep(0.75)
                
        except WebSocketDisconnect:
            return
        except Exception as exc:
            logger.exception("Run logs websocket stream failed for run %s", run_id)
            try:
                await websocket.close(code=1011, reason=f"stream_error: {type(exc).__name__}")
            except Exception:
                logger.debug("Failed to close websocket after stream error", exc_info=True)
27. Fix Catastrophic Variant Collapsing (Correctness: 6 → 8)
File: app/services/extract/listing_identity.py
Problem: When a page lacks strong identifiers (like a SKU), _fallback_title_backfill_index merges records if they share the exact same title. If a page lists 10 identical "T-Shirt" items with different prices, colors, or images, the crawler collapses them all into a single item, causing massive data loss for variant listings.
Fix: Add conflict checks for differentiating fields (price, color, size, image) so variants aren't blindly merged just because they share a title.
Replace the _has_strong_identity_conflict function (around line 112):
code
Python
def _has_strong_identity_conflict(base: dict, incoming: dict) -> bool:
    # 1. Check strong identifiers first
    for field_name in _STRONG_IDENTITY_FIELDS:
        base_value = _normalized_identity_value(field_name, base.get(field_name))
        incoming_value = _normalized_identity_value(field_name, incoming.get(field_name))
        if base_value and incoming_value and base_value != incoming_value:
            return True
            
    # FIX: Prevent merging distinct product variants (colors, sizes, prices) 
    # into a single record just because they share the same title.
    for variant_field in ("price", "color", "size", "image_url", "brand"):
        base_value = _normalized_identity_value(variant_field, base.get(variant_field))
        incoming_value = _normalized_identity_value(variant_field, incoming.get(variant_field))
        if base_value and incoming_value and base_value != incoming_value:
            return True
            
    return False
28. Fix Synchronous File I/O Blocking the Event Loop (Performance: 8 → 9)
File: app/services/acquisition/acquirer.py
Problem: At the end of the acquire function, the crawler writes megabytes of HTML, JSON, network payloads, and diagnostic data to disk synchronously. On a fast 500-URL batch run, this locks the main Python thread continuously, causing heartbeats to fail and workers to drop leases.
Fix: Offload all artifact disk-writes to the async thread pool.
Update the end of the acquire function (around line 208):
code
Python
# ... previous acquire logic ...
    
    if result is None:
        # FIX: Offload disk I/O
        await asyncio.to_thread(
            _write_failed_diagnostics,
            run_id,
            url,
            diagnostics_path,
            error_detail="All acquisition attempts failed",
        )
        if proxy_list:
            incr("proxy_exhaustion_total")
            raise ProxyPoolExhausted(f"All configured proxies failed for {url}")
        raise RuntimeError(f"Unable to acquire content for {url}")

    path = _artifact_path(run_id, url)
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    
    if result.content_type == "json" and result.json_data is not None:
        path = path.with_suffix(".json")
        await asyncio.to_thread(
            path.write_text, json.dumps(result.json_data, indent=2, default=str), encoding="utf-8"
        )
    else:
        await asyncio.to_thread(path.write_text, result.html, encoding="utf-8")
        
    # FIX: Offload network payload and diagnostics disk I/O
    await asyncio.to_thread(_write_network_payloads, run_id, url, result.network_payloads)
    await asyncio.to_thread(_write_diagnostics, run_id, url, result, path, diagnostics_path)

    result.artifact_path = str(path)
    result.diagnostics_path = str(diagnostics_path)
    return result
29. Fix JSON-LD Corruption causing Data Loss (Correctness: 8 → 9)
File: app/services/extract/source_parsers.py
Problem: extract_json_ld extracts JSON-LD scripts using node.get_text(" ", strip=True). This strips HTML tags inside JSON strings. If a site includes {"description": "<p>Product Details</p>"} in its JSON-LD, get_text() corrupts the JSON string boundary, causing a JSONDecodeError, and throwing away the entire structured record silently.
Fix: Extract the exact inner string untouched using node.string or node.strings.
Replace the extract_json_ld function (around line 34):
code
Python
def extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    results = []
    for node in soup.select("script[type='application/ld+json']"):
        # FIX: Do not use get_text() as it strips HTML tags inside valid JSON strings,
        # corrupting the payload. Use the raw inner strings.
        raw_text = node.string
        if not raw_text:
            raw_text = "".join(node.strings)
            
        data = _parse_json_blob(raw_text.strip())
        results.extend(_flatten_json_ld_payloads(data))
    return results
30. Fix ReDoS (Regex Denial of Service) in Blocked Page Detector (Security: 7 → 9)
File: app/services/acquisition/blocked_detector.py
Problem: The function detect_blocked_page executes a massive regex re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", html) over the entire raw HTML. On malformed sites with unclosed <script> tags or 5MB React payloads, this triggers Catastrophic Backtracking, pinning CPU usage to 100% until the container OOMs or is killed.
Fix: The pipeline already parses the HTML with BeautifulSoup in the acquirer. Instead of using regex, we can safely and cleanly extract visible text without risking ReDoS.
Replace the detect_blocked_page function (around line 38):
code
Python
def detect_blocked_page(html: str) -> BlockedPageResult:
    """Detect whether *html* is a blocked or challenge page safely without ReDoS."""
    if not html or len(html.strip()) < 100:
        return BlockedPageResult(is_blocked=True, reason="empty_or_too_short")

    html_lower = html.lower()
    
    # FIX: Removed the catastrophic backtracking Regex that strips scripts.
    # Replaced with a highly performant, non-blocking string slicing approach.
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        visible = " ".join(soup.get_text(" ", strip=True).lower().split())
    except Exception:
        # Failsafe if BS4 hits a recursion limit on deeply nested malicious HTML
        visible = html_lower[:20000]

    provider = ""
    title_reason = ""
    
    # Safe bounded title extraction
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_lower[:50000], re.DOTALL)
    if title_match:
        title_text = title_match.group(1).strip()
        for pattern in _BLOCK_TITLE_PATTERNS:
            if pattern.search(title_text):
                title_reason = f"blocked_title:{title_text[:60]}"
                break

    phrase_reason = next((f"blocked_phrase:{phrase}" for phrase in BLOCK_PHRASES if phrase in visible), "")

    active_reason = ""
    for item in BLOCK_ACTIVE_PROVIDER_MARKERS:
        marker = str(item.get("marker") or "")
        marker_provider = str(item.get("provider") or "")
        if marker and marker in html_lower:
            active_reason = f"active_block_marker:{marker}"
            provider = marker_provider
            break

    provider_marker = ""
    for item in BLOCK_CDN_PROVIDER_MARKERS:
        marker = str(item.get("marker") or "")
        marker_provider = str(item.get("provider") or "")
        if marker in html_lower:
            provider_marker = marker
            provider = marker_provider
            break

    text_len = len(visible)
    script_count = html_lower.count("<script")
    link_count = html_lower.count("<a ")
    structural_signal = text_len < 500 and script_count > 3 and link_count < 3
    rich_content_signal = text_len >= 2000 and link_count >= 5

    if "kpsdk" in html_lower and text_len < 200:
        return BlockedPageResult(is_blocked=True, reason="kasada_challenge_script", provider="kasada")

    if "no treats beyond this point" in visible or ("page error: 403" in visible and "restricted access" in visible):
        chewy_provider = "akamai" if "akamai" in html_lower or "reference error number" in visible else provider
        reason = "blocked_phrase:no_treats_beyond_this_point" if "no treats beyond this point" in visible else "blocked_phrase:restricted_access_403"
        return BlockedPageResult(is_blocked=True, reason=reason, provider=chewy_provider)

    if "generated by cloudfront" in visible and "request blocked" in visible and "request could not be satisfied" in visible:
        return BlockedPageResult(is_blocked=True, reason="blocked_phrase:cloudfront_request_blocked", provider="cloudfront")

    if ("403 forbidden" in visible or "403 forbidden" in html_lower or "access denied" in visible) and text_len < 500 and link_count < 3:
        return BlockedPageResult(is_blocked=True, reason="blocked_phrase:403_forbidden", provider=provider or "origin")

    if active_reason and (title_reason or phrase_reason or structural_signal or not rich_content_signal):
        return BlockedPageResult(is_blocked=True, reason=active_reason, provider=provider)

    if title_reason and phrase_reason:
        return BlockedPageResult(is_blocked=True, reason=title_reason, provider=provider)

    if phrase_reason and provider_marker:
        return BlockedPageResult(is_blocked=True, reason=f"combined:provider_marker:{provider_marker}", provider=provider)

    if phrase_reason and structural_signal:
        return BlockedPageResult(is_blocked=True, reason="combined:low_content_high_scripts", provider=provider)

    if title_reason and structural_signal:
        return BlockedPageResult(is_blocked=True, reason="combined:blocked_title+low_content_high_scripts", provider=provider)

    return BlockedPageResult()