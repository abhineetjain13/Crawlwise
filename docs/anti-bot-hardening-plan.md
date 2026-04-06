# Anti-Bot Hardening Plan

## Date
- Audit date: April 6, 2026

## Goal
- Determine what can be solved with the current crawler stack using generic controls such as pacing, retries, browser fallback, cookie persistence, consent handling, and header/transport tuning.
- Separate those controls from the remaining work needed for Cloudflare, Akamai, and similar providers in a production crawler.

## What We Tested
- `https://demo.opencart.com/`
- Current HTTP path (`curl_cffi` impersonation profiles)
- Current browser path (Playwright bundled Chromium and system Chrome channel)
- Existing host pacing, cookie persistence, consent dismissal, challenge waits, and retry behavior

## OpenCart Findings
- HTTP currently receives `403` with `server: cloudflare` and `cf-mitigated: challenge`.
- Browser automation in this environment stays on the Cloudflare interstitial even after extended waits.
- A direct Playwright probe using the Chrome channel stayed on `Just a moment...` for 45 seconds and only received `cf_chl_rc_ni`, not a usable clearance cookie.
- That means this environment does not currently solve the challenge through simple waiting alone.
- The remaining blocker is not listing extraction or schema resolution. It is challenge clearance.

## What Simple Features Can Solve
- Generic rate limiting:
  - per-host pacing
  - retry backoff
  - now also `Retry-After` header respect in the HTTP client
- Simple browser-only nuisances:
  - cookie consent banners
  - transient JS shell pages
  - weak listing pages that need a browser retry
- Session reuse:
  - if a valid, operator-approved clearance cookie already exists, the crawler can now reuse it generically

## What Simple Features Cannot Reliably Solve
- Fresh Cloudflare or Akamai challenge clearance in a hostile environment
- Provider score-based bot decisions that depend on:
  - browser fingerprint quality
  - TLS and HTTP/2 fingerprint coherence
  - IP reputation
  - persistent real-browser storage state
  - behavioral signals gathered across requests
- Pages that require a human-solved interstitial or a trusted browser profile before automation can continue

## Changes Implemented In This Slice
- Explicit cookie allowlists now work for persistence even when a cookie name would otherwise be blocked by generic prefix rules.
  - This is generic and policy-driven.
  - It enables operators to reuse cookies like `cf_clearance` only when they explicitly opt in through cookie policy.
- HTTP retry logic now respects the `Retry-After` response header.
- Acquisition diagnostics now keep a small response-header snapshot for anti-bot debugging:
  - `server`
  - `cf-mitigated`
  - `retry-after`
  - `content-type`
  - `accept-ch`
  - `critical-ch`
- OpenCart blocked runs now surface as blocked records with provider information instead of opaque acquisition failure.

## Current Practical Recommendation
- Treat OpenCart-style Cloudflare pages as `blocked` unless one of these is true:
  - the browser path actually clears the interstitial in this environment
  - a valid clearance cookie is already available and allowed by policy
  - a stronger browser/profile/proxy stack is introduced

## Production Plan

### Phase 1: Diagnostics And Safe Reuse
- Persist richer anti-bot diagnostics for every blocked acquisition:
  - final URL
  - selected response headers
  - challenge state
  - screenshot path for browser attempts
  - cookie names observed before/after challenge
- Add operator-facing visibility for:
  - provider detected
  - rate-limit vs challenge vs redirect-shell
  - whether a reusable clearance cookie exists
- Keep cookie reuse policy-driven and domain-scoped.

### Phase 2: Browser State Hardening
- Add persistent Playwright profiles per domain or per provider bucket.
- Reuse local storage, IndexedDB, service-worker state, and cookies when policy permits.
- Support a controlled manual bootstrap flow:
  - operator opens a persistent browser context
  - challenge clears once
  - crawler reuses the stored state for future runs

### Phase 3: Transport Coherence
- Align browser and HTTP client identity more tightly:
  - user-agent and client hints
  - language and locale
  - TLS and HTTP/2 fingerprint strategy
  - proxy/IP affinity across browser and HTTP retries
- Add provider-aware backoff policies for repeated 403/429 responses.

### Phase 4: Challenge-Specific Runtime
- Add provider modules for Cloudflare, Akamai, DataDome, PerimeterX, and Kasada.
- Each module should classify:
  - waitable interstitial
  - hard block
  - rate limit
  - redirect shell
- Each module should expose:
  - detection signals
  - retry guidance
  - reusable cookie names
  - storage-state policy

### Phase 5: Human-In-The-Loop Escape Hatch
- For production workflows, add a supervised acquisition mode:
  - launch persistent headed browser
  - operator clears challenge once
  - crawler harvests approved state
  - future runs reuse that state until expiry

## Engineering Constraints
- Keep all anti-bot logic generic.
- Do not add per-domain hacks in production acquisition paths.
- Domain-specific behavior must remain policy-driven through config and stored state, not hardcoded conditionals.

## Bottom Line
- For OpenCart in the current environment, simple waits, consent handling, and header tweaks are not enough to obtain a fresh Cloudflare clearance.
- What is worth implementing now is:
  - better diagnostics
  - policy-driven clearance-cookie reuse
  - rate-limit compliance
- What remains for production is a broader anti-bot system spanning transport, browser state, operator workflows, and provider-specific challenge handling.
