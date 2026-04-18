1. Acquisition Routing
Techniques: Use curl_cffi for high-performance TLS/HTTP2 impersonation to bypass edge blocks (Cloudflare, Akamai) and Playwright with stealth patches for behavioral detection (DataDome, PerimeterX)
.
Escalation Tree:
Static/Edge Protected: curl_cffi with latest browser targets
.
JS-Heavy/Behavioral: Playwright + playwright-stealth
.
Heavily Protected (DataDome/F5): Managed API or Anti-detect browsers
.
from curl_cffi import requests
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# curl_cffi: Bypasses TLS fingerprinting (JA3) at 25x speed of browser [1, 10]
def acquire_static(url):
    # Use latest supported targets: chrome146, safari260, firefox147 [11, 12]
    resp = requests.get(url, impersonate="chrome120") # [13, 14]
    return resp.text

# Playwright: Hardened context for behavioral bypass [2, 15]
async def acquire_dynamic(url):
    async with Stealth().use_async(async_playwright()) as p: # [16, 17]
        browser = await p.chromium.launch(headless=True)
        # Context hardening patches navigator.webdriver, plugins, and WebGL [2]
        context = await browser.new_context(user_agent="Mozilla/5.0...") 
        page = await context.new_page()
        await page.goto(url, wait_until="load") # [18]
        content = await page.content()
        await browser.close()
        return content
2. Structured Data Extraction
Formats: JSON-LD (SEO blocks), Microdata (itemprop tags), and __NEXT_DATA__ (hydrated JS state)
. Target Platforms: Amazon/Indeed (JSON-LD), Walmart (Microdata), Modern SPAs (NEXT_DATA)
.
import json, re
from extruct import extract
from parsel import Selector

def extract_structured(html, url):
    # extruct: Unified pass for JSON-LD and Microdata [19, 20]
    # return_html_node=True allows mapping Microdata to DOM elements [21, 22]
    data = extract(html, base_url=url, syntaxes=['json-ld', 'microdata', 'opengraph']) # [23]
    
    # parsel: Chain CSS and Regex for hydrated JS state [24, 25]
    sel = Selector(text=html)
    # Extracting __NEXT_DATA__ block common in React/Next.js sites [25]
    next_data_raw = sel.css('script#__NEXT_DATA__::text').get() # [25]
    next_data = json.loads(next_data_raw) if next_data_raw else {}
    
    return {"metadata": data, "next_js": next_data}
Failure Modes: selectolax is 30x faster but fails on malformed HTML
; parsel is slower but handles complex XPaths and Regex (.re()) for buried JS data
.
3. XHR Interception
Heuristics: Ecommerce sites often load pricing/variants via background Fetch/XHR. Intercepting raw JSON is more reliable than DOM parsing
.
async def intercept_xhr(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # Capture background API calls before goto fires [29, 30]
        captured_json = []
        async def handle_route(route):
            if "api/products" in route.request.url: # pattern match [31]
                response = await route.fetch()
                captured_json.append(await response.json()) # Capture raw JSON [32]
            await route.continue_()

        await page.route("**/*.json", handle_route) # Glob URL matching [31]
        await page.goto(url)
        await browser.close()
        return captured_json
Edge Case: Service workers can hide network events; block them by setting service_workers='block' in context settings
.
4. Normalization
Heuristics: glom for nested path resolution avoids "NoneType" errors; price-parser handles international decimal/thousand separators
.
from glom import glom, PathAccessError
from price_parser import parse_price
from w3lib.url import canonicalize_url, any_to_uri

def normalize_item(raw_data):
    # Multi-path spec: tries different keys until first-match-wins [35, 37]
    spec = {
        'name': ('product.title', 'item.name'), 
        'price_raw': ('offers.0.price', 'price'),
        'url': ('link', canonicalize_url) # w3lib: standardizes redundant slashes [38, 39]
    }
    try:
        norm = glom(raw_data, spec) # Safe declarative access [35, 37]
        # price-parser: Normalizes "$1,235.99" and "1.235,99 €" [40]
        price_obj = parse_price(norm.get('price_raw')) # [34, 40]
        norm['price'] = price_obj.amount_float
        norm['currency'] = price_obj.currency
    except PathAccessError as e: # Detailed reporting if nested keys shift [35, 37]
        return None
    return norm
5. Hidden Content Expansion
Technique: Use Accessibility Trees (ARIA snapshots) for semantic interaction. This is 95% more token-efficient than DOM parsing for LLM fallbacks
.
async def expand_content(page):
    # Click loops for "View More" or Accordions [42, 43]
    max_clicks = 5
    for _ in range(max_clicks):
        button = page.locator("button:has-text('View More'), .accordion-toggle") # [44]
        if await button.is_visible():
            await button.click()
            # Wait for accessibility tree stability (not just networkidle) [41, 45]
            await page.wait_for_timeout(1000) 
        else:
            break
    
    # Capture semantic representation of final state [41, 46]
    return await page.accessibility.snapshot() # [41, 47]
6. Zyte-Common-Items Schemas
Structure: Uses canonical field names (Product, JobPosting) to ensure identical schemas across different websites
.
from zyte_common_items import Product, JobPosting, Image, Breadcrumb

# Population Strategy: Use from_dict for validation and unknown field handling [50, 51]
product_data = {
    "url": "https://store.com/p1", # Required [52]
    "name": "Widget",
    "price": "19.99", # Standardized as string with dot decimal [53]
    "mainImage": {"url": "https://cdn.com/img.jpg"}, # Image component [54]
    "additionalProperties": [{"name": "Material", "value": "Steel"}] # Unmapped specs [55]
}

# Validation occurs during construction; unknown fields captured in _unknown_fields_dict [51]
p = Product.from_dict(product_data) # [50]
7. Full Integration
from zyte_common_items import Product, ZyteItemAdapter

async def extract_page(url):
    # Stage 1: Acquire (Behavioral escalation if needed) [2]
    html = await acquire_dynamic(url) 
    
    # Stage 2: Extract (Priority hierarchy: Structured -> JS -> DOM) [20, 21]
    raw_results = extract_structured(html, url)
    
    # Stage 3: Unify (Normalization via glom & price-parser) [37, 40]
    unified_data = normalize_item(raw_results)
    
    # Stage 4: Publish (zyte-common-items conformant) [49]
    if unified_data:
        item = Product.from_dict(unified_data)
        # ZyteItemAdapter removes empty keys for cleaner JSON output [56]
        return ZyteItemAdapter(item).asdict() 
    return None

    1. Scrapy Internals & Pipeline Components
Scrapy is an asynchronous framework built on the Twisted networking engine
.
Middleware Stack: Request and response processing is handled via a modular middleware system
. This allows for the delegation of JS rendering to external tools like scrapy-playwright
.
AUTOTHROTTLE: Scrapy includes a built-in auto-throttling mechanism to adjust crawling speed based on the load of both the Scrapy engine and the target server
.
Item Pipelines: These facilitate a staged approach to data processing, specifically for cleaning, validation, and storage
.
Note: The sources mention Scrapy's ability to handle parallel requests and link-following
, but they do not contain specific implementation details for TakeFirst/Join processors in ItemLoader or the exact logic of the AUTOTHROTTLE algorithm.
2. Crawlee Concurrency & Session Model
Crawlee for Python utilizes a resource-aware architecture built on Asyncio
.
AutoscaledPool: This component monitors system CPU and memory usage to dynamically adjust the number of concurrent browser instances, preventing infrastructure overloads
.
RequestQueue: A persistent URL queue system ensures the crawler maintains state and can recover from crashes without restarting the entire crawl
.
Session & Proxy Rotation: Crawlee integrates smart fingerprinting and proxy rotation by default, tying proxies to browser contexts so that sites see consistent "users" during a session
.
# Crawlee uses BeautifulSoup for parsing in Python [11]
from crawlee.crawlers import PlaywrightCrawler

# Concurrency is handled automatically by the internal AutoscaledPool [8]
crawler = PlaywrightCrawler(
    max_requests_per_crawl=100, 
    # Session management is built-in [9]
)
3. trafilatura: Content Extraction & Noise Reduction
Trafilatura (Italian for "wire drawing") is optimized for refining raw HTML into meaningful text
.
Heuristics: It combines algorithms like readability and jusText with custom heuristics to balance precision (limiting noise) and recall (including valid parts)
.
Output Formats: Supports plain text, Markdown, CSV, JSON, and XML-TEI
.
Fast Mode: A specialized mode that skips slower fallback algorithms for a ~50% increase in execution speed
.
Note: Sources document that it removes recurring elements like headers, footers, and sidebars
 but do not explicitly detail failure modes on "sparse pages."
4. Parsel: Advanced Selector Patterns
Parsel is the engine behind Scrapy, utilizing lxml for high-performance parsing
.
Chaining: It allows for the chaining of .css() and .xpath() methods for precise extraction
.
Regex: Supports .re() and .re_first() for extracting data from text nodes or inline JavaScript
.
Failure Modes: Regex methods return lists of strings and cannot be chained
. Because it relies on lxml, the results may occasionally differ from what is seen in a standard web browser
.
from parsel import Selector
# Chaining CSS and XPath
sel = Selector(text=html)
img_src = sel.css('img').xpath('@src').getall() # [21]

# Extracting from JS strings via Regex
price = sel.re_first(r'price:\s*(\d+)') # [19]
5. w3lib: HTML & URL Utility Inventory
Beyond canonicalization, w3lib provides extensive sanitization tools
.
Encoding Detection: html_to_unicode() attempts to guess encoding using BOM, HTTP headers, and meta tags
.
HTML Cleaning:
remove_comments(text): Strips HTML comments
.
remove_tags(text, keep=()): Removes all tags except those specified
.
replace_entities(text): Converts &nbsp; or &#nnnn; into unicode characters
.
Whitespace: strip_html5_whitespace(text) removes leading/trailing space characters as defined by the HTML5 standard for URLs
.
6. Playwright Session Management
Playwright enables the persistence of browser states to avoid repetitive login flows
.
Storage State: browser_context.storage_state() captures cookies and localStorage into a file
.
Restoration: Use browser.new_context(storage_state="state.json") to restore the environment
.
Note: The sources do not specify which cookie types "should never be persisted."
7. Service Worker Interference
Service workers can intercept network events, making them invisible to Playwright's page.route()
.
Detection/Handling: If network events are missing, users should set service_workers='block' in the browser context
.
Note: The sources focus on blocking as the primary solution and do not document other detection techniques.
8. jmespath: XHR Payload Querying
JMESPath provides a declarative language for navigating nested JSON structures
.
Projections: * syntax for array navigation
.
Filtering: [? <expression>] for conditional selection
.
Example Patterns:
Ecommerce Variants: products[*].variants[*].price
Job Locations: jobs[?remote == 'true'].location
Nested Metadata: metadata.*.author_name
Multi-key Projection: people[].[first_name, last_name]
Negative Indexing: results[-1].id
9. Firecrawl: Markdown Pipeline
Firecrawl's conversion pipeline is designed for LLM readiness
.
Noise Removal: Automatically strips navigation menus, ads, popups, and cookie banners while preserving the main content
.
Token Efficiency: Its markdown output uses ~67% fewer tokens than raw HTML
.
Semantic Understanding: Unlike trafilatura’s rule-based approach, Firecrawl uses AI-powered semantic extraction to interpret the meaning of elements, making it more resilient to layout changes
.
10. Rate Limiting & Politeness
Scrapy: Uses the AUTOTHROTTLE extension to manage request intervals based on server latency
.
Crawlee: Uses AutoscaledPool to manage concurrency based on the local machine's resource limits (CPU/RAM)
.
Colly (Reference): Mentions per-domain rate limiting and robots.txt compliance
.
General Rule: Politeness requires checking robots.txt and using realistic User-Agents
.