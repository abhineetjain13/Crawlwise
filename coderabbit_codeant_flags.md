Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 388 - 403, The function _is_sequential_integer_run may raise on Unicode digit characters because stripped.isdigit() can be True for characters int() can't parse; wrap the int(stripped) conversion in a try/except ValueError (return False on exception) to guard against non-parseable digits, and remove the redundant if not ints check since length >=5 is already enforced; keep the sort and contiguous-run check as-is.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 486 - 504, The token set _QUANTITY_ATTR_TOKENS contains compound entries (e.g., "item-count", "number_of_items") that never match because _select_is_quantity_node splits attribute values on hyphens/underscores; update the function to either (a) expand _QUANTITY_ATTR_TOKENS into normalized component tokens (e.g., "item", "count", "number", "items") or (b) also check a normalized attribute string with hyphens/underscores removed (e.g., value.replace("-", "").replace("_","")) before/alongside splitting, and keep references to _QUANTITY_ATTR_TOKENS and _select_is_quantity_node when making the change.

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md at line 17, The variants object for the Button component has duplicate class strings for the 'primary' and 'accent' keys; locate the variants definition (the object with keys 'primary' and 'accent') and either replace the 'accent' value with the intended distinct CSS class string for accent styling or remove the 'accent' key and update all call sites to use 'primary' instead; ensure you update any usages of the 'accent' variant (e.g., <Button variant="accent">) to the new key or to 'primary' and run a quick search for 'variant:"accent"'/'variant=\'accent\'' to catch all callers.

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md at line 9, The dropdown shows an option { value: "harness", label: "harness" } but the onChange handler only handles "user" and "admin", so selecting "harness" is ignored; choose one fix and implement it: either remove the "harness" entry from the options array used by the Dropdown component, or mark that option as disabled in the same options array if per-option disabled is supported, or extend the Dropdown onChange arrow to handle "harness" by calling updateUser(user.id, { role: "harness" }) and ensure updateUser accepts that role; update the options array, the Dropdown onChange handler, and the updateUser call accordingly (look for the Dropdown component, the options array definition, the onChange arrow, and updateUser references in the users page).

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md at line 5, The forced_engine handling in crawl_fetch_runtime.py currently silently ignores non-"real_chrome" values when reading context.forced_browser_engine; update the logic in the block that inspects context.forced_browser_engine to validate the supplied value against your allowed_engines list (e.g., contains "real_chrome", "chromium", etc.), and either (A) accept and return the forced_engine when it matches a supported engine (return the single-engine list or call _append_engine_once as existing code uses), or (B) fail-fast by raising or logging a clear error/warning that includes the offending forced_engine and context.forced_browser_engine so callers like fetch_page aren’t silently ignored; modify the code paths around forced_engine/allowed_engines/_append_engine_once to perform this explicit validation and error handling.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/admin/users/page.tsx around lines 115 - 129, The JSX for the user row is malformed: close the email cell <td> that currently contains user.email, remove the stray standalone "/>" and move the <Dropdown> into its own <td> so the table cells are well-formed; ensure the <Dropdown> keeps its props (value={user.role}, onChange calling updateUser(user.id, { role }), disabled={pendingUserId === user.id}, options, className) and nothing else is altered (preserve user.email cell, Dropdown props and surrounding <td> tags).

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/product-intelligence/page.tsx around lines 338 - 347, The "Select all" checkbox checked state should ignore falsy candidate URLs to match toggleAllUrls behavior: update the checked expression on the input so it only considers truthy candidate URLs (e.g., use filteredCandidates.filter(Boolean) or map to candidate.url and filter(Boolean)) when computing length and when calling .every(... includes(selectedUrls)), ensuring the check uses the same filtering logic as toggleAllUrls and still requires > 0 truthy URLs before marking checked.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/shared.tsx around lines 600 - 611, The replacement currently slices the path to 55 chars into slug and uses slug.length >= 55 to decide adding an ellipsis, which incorrectly appends “…” when the original path is exactly 55; change the logic in the msg.replace callback (the function using parsed, slug, verb, url) to compute the originalPath = parsed.pathname + parsed.search, compute truncated = originalPath.slice(0, 55), and only append the ellipsis when originalPath.length > 55 (not when truncated.length >= 55), then use truncated in the returned string.

- Verify each finding against the current code and only fix it if needed.

In @frontend/package.json around lines 56 - 58, The package.json override forcing "postcss": "^8.5.10" can break compatibility/security with TailwindCSS v4 and Next.js; instead, remove or update the overrides entry and determine the correct postcss version by reproducing the dependency conflict: run npm/yarn pnpm list to find which package requires an older postcss, capture the build error that prompted this override, then update the override to the minimum postcss version compatible with Tailwind v4 (or remove it and upgrade the transitive dependency or bump the dependent package), and verify by rebuilding; check/change the "overrides" -> "postcss" entry in package.json and adjust lockfile accordingly.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Non-patchright engines now skip the init script entirely, breaking previous browser fingerprint behavior.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 157-157

2. possible bug: Switching browser exception imports to patchright may break runtime compatibility if the backend still expects Playwright.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 11-11

3. possible bug: Using Patchright exception classes may break timeout/error handling if the browser stack is still Playwright-based.
   Path: backend/app/services/acquisition/browser_readiness.py
   Lines: 50-50

4. possible bug: Catching every exception from `cookies_fn([url])` can mask real cookie lookup failures.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 407-407

5. possible bug: Real Chrome is now forced through the Patchright backend.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 250-250

6. possible bug: Removing legacy keyword-argument fallbacks can break older provider implementations.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1017-1017

7. logic error: Unknown browser engines are now normalized to Patchright instead of Chromium.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 131-131

8. possible bug: Switching to a different browser exception class can break existing error handling when the package is unavailable.
   Path: backend/app/services/acquisition/traversal.py
   Lines: 14-14

9. possible bug: Removing established runtime settings breaks existing configuration consumers.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 187-187

10. logic error: Forced chromium requests are now ignored instead of being honored as an alias.
   Path: backend/app/services/crawl_fetch_runtime.py
   Lines: 971-971

11. possible bug: Removing Chromium from fallback attempts can make browser escalation fail where it previously succeeded.
   Path: backend/app/services/crawl_fetch_runtime.py
   Lines: 929-929

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.