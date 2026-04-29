Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_identity.py around lines 325 - 339, _safely_clone_fingerprint currently returns the original raw_fingerprint on copy failures which allows callers like _align_raw_fingerprint_to_user_agent_platform to mutate shared objects (e.g., setting navigator.platform) and corrupt _RUN_BROWSER_IDENTITIES; change _safely_clone_fingerprint to return None on failure (or raise a specific CloneError), and update callers to explicitly handle that case by either skipping mutation, logging a warning, or creating a safe shallow clone of only the navigator before mutating; ensure handling covers both the copy failure and the navigator-copy fallback so the original raw_fingerprint is never modified.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_proxy_config.py at line 31, Replace the use of the original parsed.scheme when building the server URL with the normalized, lowercased scheme variable (the one created for validation) so the server string uses the normalized scheme; modify the assignment that sets server (which currently uses parsed.scheme and proxy_host_port(parsed)) to use that normalized scheme variable together with proxy_host_port(parsed) to ensure consistent, lowercase scheme in the URL.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_proxy_config.py around lines 33 - 36, The current logic sets config["username"] when parsed.username is truthy but sets config["password"] whenever parsed.password is not None, allowing a password without a username; update the condition so password is only added when a username is present (e.g., require parsed.username truthy before assigning config["password"]) or use consistent presence checks for both parsed.username and parsed.password; modify the assignments around parsed.username, parsed.password, and config to enforce that password is only included if username was set.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_proxy_config.py around lines 58 - 61, The current conditional returns raw_proxy when scheme or hostname is missing which can leak credentials; change the logic to detect credentials (parsed.username or parsed.password) before the validity check and redact them regardless of URL validity: if parsed.username or parsed.password, construct and return a redacted string (e.g., replace credentials portion with "REDACTED" or remove userinfo) instead of returning raw_proxy, otherwise fall back to the existing validity check (the conditional referencing parsed.scheme, parsed.hostname, parsed.username, parsed.password and raw_proxy).

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: The backend install command in the README does not match the project’s actual setup flow.
   Path: README.md
   Lines: 74-74

2. possible bug: The README advertises frontend commands that are not exposed by the repository’s root scripts.
   Path: README.md
   Lines: 127-127

3. possible bug: Pagination happens after loading all summaries, causing avoidable full-table reads.
   Path: backend/app/api/selectors.py
   Lines: 42-42

4. possible bug: New summary response model may not match the actual selector summary payload.
   Path: backend/app/schemas/selectors.py
   Lines: 8-8

5. logic error: Header and navigation expanders can now be skipped even when they are valid collapsible controls.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 273-273

6. logic error: Failure diagnostics are no longer populated on browser fetch errors.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1441-1441

7. possible bug: _storage_state_entry_count() counts arbitrary iterables by materializing them.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 476-476

8. logic error: Refactoring marker extraction can silently stop challenge signatures from matching.
   Path: backend/app/services/acquisition/runtime.py
   Lines: 692-692

9. state inconsistency: Returning the original fingerprint when cloning omits isolation.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 347-347

10. possible bug: The site path regex can extract the wrong site identifier.
   Path: backend/app/services/adapters/oracle_hcm.py
   Lines: 193-193

11. possible bug: The job-id parser can extract the wrong identifier from Oracle HCM detail URLs.
   Path: backend/app/services/adapters/oracle_hcm.py
   Lines: 242-242

12. logic error: The Oracle HCM config regex will miss valid page variants and fail to extract configuration.
   Path: backend/app/services/config/extraction_rules.py
   Lines: 150-150

13. possible bug: A newly added timeout setting is validated as strictly positive, which may reject a disabled value of 0.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 393-393

14. logic error: Removing the ecommerce variant DOM-completion branch can skip variant backfill.
   Path: backend/app/services/detail_extractor.py
   Lines: 877-877

15. logic error: Shared parameter resolution can silently change precedence between plan and config values.
   Path: backend/app/services/pipeline/core.py
   Lines: 141-141

16. possible bug: Directly mutating shared runtime settings without explicit restoration can leak state between tests.
   Path: backend/tests/services/test_browser_expansion_runtime.py
   Lines: 2165-2165

17. possible bug: Shared configuration mutation makes the AOM timeout test order-dependent.
   Path: backend/tests/services/test_browser_expansion_runtime.py
   Lines: 2234-2234

18. possible bug: Moving artifact loading to a shared helper can break fixture resolution if its fallback path differs.
   Path: backend/tests/services/test_crawl_engine.py
   Lines: 11-11

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.