
Logic & Complexity Audit Document: CrawlerAI
1. System Complexity Summary
What this system is actually trying to do:
At its core, CrawlerAI is an ETL (Extract, Transform, Load) pipeline. It takes a URL, fetches the raw bytes (HTTP or headless browser), parses those bytes into a structured schema (JSON or Dict), saves it to a database, and allows a user to export it.
The irreducible core problem it solves:
Defeating basic bot-protection (WAFs/CAPTCHAs).
Handling JavaScript-heavy Single Page Applications (SPAs).
Mapping chaotic HTML/JSON into a predictable schema (Jobs or E-commerce).
The core-to-scaffolding ratio:
The ratio of core logic to supporting scaffolding in this codebase is roughly 1:6.
For every line of code actually extracting data, there are six lines of code dedicated to heuristic scoring, routing, candidate reconciliation, configuration metaprogramming, autonomous browser planning, and "memory" management. The system has evolved from a crawler into an autonomous, self-healing, AI-agentic framework with its own internal CMS for CSS selectors.
2. Complexity Ledger
Layer	What it does	Is this necessary?	Simpler alternative if not
Acquisition (curl → Playwright)	Waterfall fetch to bypass bot protection and render SPAs.	Yes.	N/A (Standard modern scraping pattern).
Detection (Blocked Pages)	Regex/string matching to detect CAPTCHAs/WAFs.	Yes.	N/A.
Platform Adapters	Hardcoded extraction logic for known sites (Amazon, Workday, etc.).	Yes.	N/A (Direct adapters are always the most robust path).
Discovery Manifest	Parses the page into 10+ buckets (JSON-LD, NextData, Network, etc.) before extraction.	No.	Pass the BeautifulSoup object, URL, and raw HTML directly to extractors. Stop creating proprietary intermediate ASTs.
Candidate Extraction Engine	Pulls 9 different possible values for a single field, scores them, and picks the best.	No.	Chain of Responsibility: Try Adapter → Try JSON API → Try JSON-LD → Try DOM. Return the first valid hit.
Evidence Graph	Maps relationships between network payloads, DOM, and actions.	No.	Over-engineered abstraction. It solves no immediate extraction problem that a direct JSON/DOM parse doesn't solve.
Field Activation Planner	Dynamically decides which browser buttons to click based on semantic field names.	No.	Execute a generic JS snippet to click all <details>, [aria-expanded="false"], and button tags before freezing the DOM.
Knowledge Base (22 JSONs)	Externalizes regexes, constants, and logic rules into JSON files.	No.	Standard Python modules (config.py with Dataclasses/Enums). You lose type safety, syntax highlighting, and IDE refactoring by stuffing regexes in JSON.
LLM Subsystem	Custom provider routing, prompt templating, token counting, and cost logging.	Partial.	Use LiteLLM or LangChain to handle provider routing and token counting.
Selector Subsystem (UI/CRUD)	Full database-backed CRUD for managing CSS/XPath selectors per domain.	No.	If a site layout changes, developers should update the adapter code and deploy. Building a UI to patch crawler logic at runtime is a massive maintenance trap.
Site Memory	Caches dynamically discovered LLM selectors to apply to future runs automatically.	No.	Highly fragile. If the site changes, the "memory" applies stale XPaths, causing silent data corruption. Rely on code-backed adapters.
Review System	Allows users to manually review/override extracted fields.	Partial.	Keep the UI, but drop the complex "Confidence Score" and "Source Trace" tracking unless users are actively training machine learning models with it.
Worker / Concurrency	In-process polling of the DB using FOR UPDATE SKIP LOCKED.	Yes.	Perfectly fine for small-to-medium scale without adding Redis/Celery.
3. Over-Engineering Flags
Flag 1: The Heuristic "Candidate" Extraction Engine
What it is: In service.py, the system doesn't just look for a product title. It looks for a title in JSON-LD, Microdata, Next.js props, DOM selectors, open graph tags, and network payloads simultaneously. It creates a list of all "candidates", passes them through an extensive scoring algorithm (_field_quality_score), and attempts to mathematically deduce the best one.
What problem it solves: Trying to build a "one-size-fits-all" generic scraper that magically works on any unknown website.
The Reality: Heuristic soups fail unpredictably. When a bad title is extracted, debugging why the scoring algorithm preferred it over a good title requires tracing through 1,500 lines of nested logic.
Simpler version: A strict hierarchy. 1. If Adapter exists, use it. 2. Else if __NEXT_DATA__ exists, use it. 3. Else if JSON-LD exists, use it. 4. Else use LLM fallback. Stop at the first success.
Flag 2: JSON-Based Metaprogramming (Inner-Platform Effect)
What it is: 22 JSON files acting as a database of regexes, aliases, and schemas, all loaded through a central pipeline_config.py God Module.
What problem it solves: Allowing non-developers to supposedly tune crawler behavior without deploying code.
The Reality: Non-developers do not write lookahead regexes for salary ranges ((?i)(?:(?:[$€£₹]|usd...). Developers will be the ones editing these JSON files, but without the benefit of Python's syntax checking, linting, or test mocking.
Simpler version: Move all configuration into typed Python files (e.g., rules.py).
Flag 3: Field Activation Planner & Autonomous Browser Actions
What it is: The system attempts to dynamically map requested output fields to DOM click actions (e.g., "User wants 'specifications', therefore I must find and click buttons labeled 'specs' or 'details'").
What problem it solves: Expanding hidden content (accordions/tabs) before parsing the HTML.
The Reality: Mapping semantic intent to DOM clicks is notoriously brittle.
Simpler version: A blunt-force Playwright script that simply finds all elements matching button, summary, [role="tab"] and clicks them, waits 500ms, and dumps the HTML.
Flag 4: Site Memory & Auto-Promoted Selectors
What it is: If the LLM discovers an XPath for a missing field, it saves it to a site_memory table and automatically applies it to future URLs on that domain.
What problem it solves: Reducing LLM costs and latency on subsequent crawls.
The Reality: Websites A/B test layouts constantly. An XPath discovered on /product/A might completely fail on /product/B, or worse, silently extract the wrong data. Building a self-modifying crawler introduces non-deterministic behavior.
Simpler version: Use LLM extraction as a realtime fallback. If a domain is crawled frequently enough to worry about LLM costs, a developer should write a dedicated Adapter for it.
4. Hidden Coupling Risks
The pipeline_config.py God Object: Nearly every file in the extraction subsystem imports from this single massive configuration module. Because it loads runtime JSON, modifying a JSON file to fix an issue on one website can silently break extraction heuristics for hundreds of other websites.
The DiscoveryManifest -> ReviewBucket Pipeline: Data transformations are coupled tightly across conceptual boundaries. The network interception layer parses JSON arrays, which feeds into the DiscoveryManifest, which feeds into the CandidateExtractor, which feeds into the ReviewBucket, which feeds into the SiteMemory. A failure in parsing a GraphQL edge deeply impacts the user-facing UI confidence scores.
Database schema coupling to LLM state: The CrawlRecord.source_trace JSON column stores massive amounts of proprietary meta-state (LLM cleanup suggestions, candidate scores, manifest traces). As the LLM logic changes, these massive JSON blobs will become impossible to migrate or query effectively, bloating the SQLite database rapidly.
5. The Right Size Question
Does this system need a Platform Resolver? Yes, but as a simple Regex router in Python, not a JSON configuration file.
Does it need an Evidence Graph? No. It adds immense cognitive overhead for zero tangible extraction benefit.
Does it need a Field Activation Planner? No. Brute-force clicking of standard accordion/tab selectors in Playwright is 95% as effective and 10x simpler.
Does it need 22 JSON config files? No. It needs 3-4 Python files containing standard dataclasses and compiled regexes.
Does it need an LLM subsystem built-in? No. The LLM integration is good, but building a custom prompt registry, cost tracker, and provider multiplexer is reinventing the wheel. Use a lightweight library like LiteLLM.
Does it need a Selector management UI? No. Selectors belong in code (Adapters). Exposing them to a UI creates a brittle "no-code" trap that breaks silently.
Does it need Site Memory? No. Crawlers should be stateless between runs. Stateful crawlers that learn bad XPaths become corrupted over time.
At what scale do these earn their cost? A selector UI and Site Memory only make sense at massive enterprise scale (e.g., scraping 100,000 different domains daily) where deploying code for every site is impossible, and you have a dedicated QA team reviewing the auto-generated XPaths. For known ATS and E-commerce sites, adapters are infinitely superior.
6. What To Keep, Cut, Defer
Keep (Necessary & Well-Designed)
Waterfall Acquisition: The curl_cffi → WAF detection → Playwright escalation path is excellent and necessary for modern scraping.
Platform Adapters: Explicit code adapters for Indeed, Shopify, Workday, etc., are exactly how web scraping should be done.
JSON API Extraction: The logic to find arrays of objects in intercepted XHR requests is a highly effective way to bypass DOM scraping entirely.
In-Process Worker: SELECT FOR UPDATE SKIP LOCKED is a great, lean choice for job queuing without Redis.
Cut or Simplify Now (Complexity not earning its keep)
22 JSON Config Files: Convert immediately to native Python code.
Site Memory & Selector CRUD: Rip out the database tables and UI for this. Hardcode fallbacks.
Heuristic Candidate Scoring: Replace the 1000-line scoring engine with a simple first-match-wins hierarchy (API > JSON-LD > Adapter > DOM > LLM).
Evidence Graph & Discovery Manifest: Pass the HTML and XHR payloads directly to extractors.
Defer Until Validated
LLM Cost Logging: Unless you are currently blowing through thousands of dollars in API credits, drop the custom cost tracking.
Review System Confidence Scores: Keep the ability for a user to edit a record, but drop the complex 1-10 confidence scoring algorithm until users specifically ask for ML-style confidence bounds.
7. Recommended Simplest Viable Architecture
If starting from the working core today, the leanest viable architecture looks like this:
Router: Input URL → Regex match → Select Platform Adapter (e.g., WorkdayAdapter) OR GenericAdapter.
Acquisition: Fetch with curl_cffi. Check for WAF/CAPTCHA or SPA shell (< 2% visible text). If blocked/SPA, refetch with Playwright.
Extraction (Adapters): If a specific adapter was chosen, execute it. Return a list of standard dictionaries.
Extraction (Generic):
Step A: Check XHR payloads for JSON arrays. If found, map keys and return.
Step B: Check DOM for JSON-LD. If found, map keys and return.
Step C: Pass HTML to LLM with instructions: "Extract an array of job/product records from this HTML matching this JSON schema." Return result.
Storage: Save dictionaries to SQLite.
Export: Simple API endpoints to convert DB rows to JSON/CSV.
The Bottom Line
This system is severely over-engineered in its extraction and orchestration layers. While the acquisition layer correctly solves real-world scraping problems (WAFs, SPAs), the data extraction layer suffers from intense "Inner-Platform Effect"—the developers have built a rules engine, an autonomous browser agent, a heuristic scoring system, and a dynamic configuration database to avoid writing standard Python scraping scripts. By deleting the Evidence Graph, Site Memory, and JSON configuration files in favor of standard Python Adapters and simple hierarchical fallbacks, you could safely delete 40% of this codebase while making it significantly faster, more deterministic, and infinitely easier to debug.