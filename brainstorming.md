Let me check:

The adapters directory
The traversal/acquisition code
The TEST_SITES.md file for existing coverage
Platform detection/config
Let me start by reading relevant files.

Let me investigate the current state of adapters, platform config, and the test sites file.

Read c:\Projects\pre_poc_ai_crawler\TEST_SITES.md
Globpattern: "backend/app/services/adapters/**/*.py"
Found 19 files
Let me look at the existing adapters for ADP, Greenhouse, iCIMS, and SaaSHR - and also check for UltiPro/Workday adapters. I also need to understand the platform registry and how adapters are matched.

Let me read the relevant adapters and platform registry simultaneously.

Read c:\Projects\pre_poc_ai_crawler\backend\app\services\adapters\registry.py
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\adapters\adp.py
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\adapters\icims.py
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\adapters\saashr.py
Now let me look at the platform config and the base adapter to understand how platform family matching works. I also need to check if there's a Workday adapter since smithnephew.wd5.myworkdayjobs.com is a Workday URL, and a UltiPro adapter for recruiting.ultipro.com.

Now let me check the platform config and base adapter to understand URL matching, and look for UltiPro/Workday adapters.

Read c:\Projects\pre_poc_ai_crawler\backend\app\services\config\platforms.json
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\adapters\base.py
Now I have a clear picture. Let me analyze the five sites:

recruiting.ultipro.com/KAP1002KAPC/JobBoard/... - UltiPro/UKG

Platform config exists (ultipro_ukg) but there's NO adapter class for it in the registry! The _ADAPTER_FACTORIES dict doesn't have "ultipro_ukg". The platform config lists "adapter_names": ["ultipro_ukg"] but there's no UltiProAdapter class.
workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=... - ADP WorkForceNow

Has an adapter, but the board is an Angular SPA that requires browser rendering. The content is likely in a shadow DOM or heavily JS-rendered, and the selector .current-openings-item needs verification. Browser rendering is configured but I need to confirm it's actually being triggered.
smithnephew.wd5.myworkdayjobs.com/External - Workday

Platform config exists (workday) but NO adapter! No adapter_names listed and no adapter class in the registry. Workday uses a JSON API but there's no implementation to handle it.
atlasmedstaff.com/job-search/ - Atlas MedStaff (custom board)

No adapter exists, likely a custom ATS. I need to either identify the actual platform or add DOM extraction logic.
secure7.saashr.com/ta/6208610.careers?CareersSearch=&ein_id=118959061&career_portal_id=6062087&InFrameset=1&HostedBy=lcbhs.net&ShowJob=587687242 - SaaSHR single job detail

Has a SaaSHR adapter, but the URL is a detail page with ShowJob=587687242, while try_public_endpoint is designed for listing pages and calls the job-requisitions API, which returns empty results because it doesn't handle detail URLs.
For the fixes, the UltiPro adapter is missing entirely even though the platform config references ultipro_ukg. I need to create an adapter that uses UltiPro's REST API, which has a public endpoint for fetching open jobs from a job board using the company ID extracted from the URL. I'm realizing the ADP adapter might be failing because Angular hasn't finished rendering the job listings by the time we're trying to scrape them, even though the browser is enabled. The selector .current-openings-item could also have changed in recent versions, or the page structure might be different now. Looking at the URL parameters, the selectedMenuKey=CurrentOpenings suggests the page should load that section, but I need to figure out if there's a better way to detect when the content is actually ready or if I should try a different selector approach. The real issue is that ADP uses Shadow DOM web components like sdf-link, which standard parsers can't access—I need to either intercept the network requests where the actual job data lives, extract data from the page's internal state, or find selectors that work on the light DOM wrapper instead. The simplest approach might be refining the selectors to target elements outside the shadow boundary, though the query parameter selectedMenuKey=CurrentOpenings suggests the page structure is tied to specific navigation states. The ADP API endpoint structure is still unclear without the exact parameters, so I'll work with what's visible in the current implementation. For Workday, the API follows a predictable pattern across their job board URLs—I can construct the endpoint using the company subdomain and the standard /External/1/dd/jobSearchResult path with pagination parameters. I need to build out a proper Workday adapter using that API structure. Now looking at Atlas MedStaff—they're running a custom job board at their /job-search/ endpoint, so I'll need to rely on browser rendering and JSON-LD extraction since their API isn't a known platform. Let me reconsider what the user actually mentioned about which site has the linking issue.

Mapping out the five sites: UltiPro has no adapter, ADP's having browser rendering problems, Workday needs a proper adapter built, Atlas MedStaff is custom and unknown, and SaaSHR is the one returning only links instead of full job details. The SaaSHR adapter's extract() method calls try_public_endpoint() which seems to be where the issue originates.

The problem with SaaSHR is that when a detail page URL comes in with the ShowJob= parameter, the adapter doesn't recognize it's a detail request and instead tries to fetch from the listing API. I need to detect that parameter and handle it differently to pull the actual job details.

So my action plan: build adapters for UltiPro and Workday, fix ADP's browser handling or data extraction approach, investigate Atlas MedStaff's actual structure, and patch SaaSHR to detect and properly handle detail page requests. For Workday, I need to extract the tenant from the subdomain and construct the API endpoint correctly—the path structure is https://{host}/wday/cxs/{tenant}{external_path}/jobs where the tenant comes from the subdomain prefix.

Now I'm checking how ADP's platform detection and readiness validation work to see if the browser rendering approach is actually functioning as intended.

Let me check platform policy and the greenhouse adapter to understand patterns, then look at what's missing.

Read c:\Projects\pre_poc_ai_crawler\backend\app\services\platform_policy.py
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\adapters\greenhouse.py
Now I have a clear picture of all five failure modes. Let me analyze each:

UltiPro (recruiting.ultipro.com): The platform config (ultipro_ukg) lists "adapter_names": ["ultipro_ukg"] but:

No UltiProAdapter class exists
_ADAPTER_FACTORIES doesn't have "ultipro_ukg"
The adapter will silently be skipped with a warning, falling through to generic DOM extraction
Fix: Create ultipro.py adapter + register in _ADAPTER_FACTORIES
ADP (workforcenow.adp.com): The adapter exists but the board is a heavily JS-rendered Angular SPA with Shadow DOM components that the current selector strategy can't penetrate, and while requires_browser: true is set, it may not render those Shadow DOM elements accessibly—I need to explore whether ADP exposes a network API for extracting the job data instead. selectedMenuKey=CurrentOpenings. Modern ADP boards render through Angular with SDF web components. The real fix is that ADP WorkForceNow boards use a JSON REST API, but the adapter has requires_browser: true since Playwright's page.content() won't pierce Shadow DOM to expose sdf-link elements.

The actual problem is simpler: while the domain pattern workforcenow.adp.com should match in can_handle(), the extraction fails because ADP's SDF web components render content in Shadow DOM that isn't accessible in the rendered HTML, and the selector .current-openings-item likely doesn't exist in their current design. Looking at job data in embedded JSON scripts, then I need to handle Workday by creating an adapter that uses their CXS API. For Atlas MedStaff, I'm trying to figure out their backend—they're a healthcare staffing company with a custom job board, likely powered by something like Bullhorn, but I'd need to inspect their actual network requests to know for sure.

Since the generic job-search URL pattern would trigger platform detection but won't set the browser requirement flag, the real issue is that JavaScript-rendered job boards need browser rendering enabled. This is more of a user configuration concern—they'd need to set advanced_enabled: true in their crawl settings rather than a code fix I can implement.

Moving on from Atlas MedStaff, I'm looking at the SaaSHR detail page issue. The adapter currently fetches the full job listing regardless of whether a specific job ID is requested via the ShowJob parameter. I need to detect when that parameter is present and return just that single job record instead of the entire listing.

For the UltiPro adapter, I'm building out a new implementation that works with their JSON API endpoint structure...

Writing UltiPro adapter...

Now for ADP, the challenge is that their SDF web components may be rendering content in the shadow DOM, which isn't directly accessible through standard HTML parsing. I'm checking whether the job data is embedded in the page source as JSON or if I need to handle the rendering differently.

For Workday, I'm building an adapter that uses their CXS API endpoint, extracting the tenant name from the subdomain and constructing the proper request format with pagination and search parameters.

For SaaSHR's detail mode, I need to detect when a job ID parameter is present and either pull that specific job from the listing results or make a targeted API call to fetch just that job's details.

Now I'm thinking through the platforms.json configuration changes needed—I should add the workday adapter to the workday family and clarify the ultipro naming convention, since the current setup references ultipro_ukg but the adapter registry might expect a different key format.

For the implementation, I need to create the UltiPro and Workday adapters, update the registry to include them, fix the SaaS HR detail mode, improve how ADP handles SDF web components, update the platforms configuration, and document the new test sites.

Starting with the UltiPro adapter, I'm looking at how their public recruiting boards structure their API endpoints... I'm extracting the response structure from UltiPro's API, which returns job postings with fields like title, description, number of openings, location, and posting date. Now I'm looking at the Workday adapter pattern, which uses a different POST endpoint with a CXS API that accepts facets and search parameters, returning job postings with title, external path, and location information.

For Workday tenant extraction, I need to parse the subdomain from URLs like smithnephew.wd5.myworkdayjobs.com where the first part is the tenant identifier. The site path comes from the URL structure, like /External.

For the SaaSHR adapter, I'm realizing the current implementation fetches all jobs but when a specific job ID is passed via the ShowJob= parameter, I should filter the results to return just that single record instead of the entire list.

Actually, a cleaner approach would be to detect the detail mode directly in the extraction logic and route to a specialized handler that either queries the listing API with a filter or hits a dedicated single-job endpoint if available. The SaaSHR API likely supports a direct job requisition endpoint that takes the job ID as a parameter, which would be more reliable than filtering the full list.

Now I'm looking at how the ADP adapter extracts job listings using CSS selectors to identify job cards and title elements.

The issue is that ADP's Shadow DOM components like sdf-link don't expose their content when Playwright renders the page, so I need to look for the job data in other places—either in embedded script tags containing window state, JSON data structures like __NEXT_DATA__, or by capturing network requests. The recruitment URL pattern suggests this is the older MDF-based UI, but the newer SDF interface uses a different URL and loads jobs through Angular XHR calls after rendering. The real problem is likely that the readiness check isn't actually waiting for the job listings to load before considering the page ready. I need to trace through how readiness_domains and readiness_path_patterns are actually being used in the acquisition code to see if they're triggering a wait for specific elements to appear on the page.

Let me check the fetch runtime for readiness and browser logic, and the traversal code.

Read c:\Projects\pre_poc_ai_crawler\backend\app\services\crawl_fetch_runtime.py
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\acquisition\browser_pool.py
Now I have enough context to proceed. Let me now implement all the fixes. Here's my plan:

UltiPro adapter: Create ultipro.py with the UKG/UltiPro job board JSON API

Workday adapter: Create workday.py with the Workday CXS API

SaaSHR: Fix detail mode (when ShowJob= param present)

ADP: Improve selectors and add JSON script fallback

platforms.json: Add workday adapter_names, fix ultipro adapter key

registry.py: Register new adapters

TEST_SITES.md: Add the new test sites

For atlasmedstaff.com, the URL pattern doesn't match any known ATS systems I can identify, so it's likely a custom implementation or staffing-specific platform. Without being able to inspect the network requests, I can't create a specific adapter, but the browser rendering should handle it if advanced mode is enabled.

The real issue here is that atlasmedstaff would match the generic job board pattern with /job-search/ in the URL, which returns generic_jobs as the platform family without the requires_browser flag set to true. This means the crawler defaults to HTTP instead of using the browser, which is why it's failing on a JavaScript-heavy site. I need to either add a specific entry for atlasmedstaff.com in the platforms configuration or update the generic job board logic to enable browser rendering by default.

However, adding site-specific entries violates the rule against hacks in generic paths. The better approach is to focus on the four definitive platform failures (UltiPro, ADP, Workday, SaaSHR) and note that for atlasmedstaff.com, users would need to enable advanced_enabled: true in their crawl settings to force browser rendering.

Now I'm implementing the fixes. For SaaSHR, the issue is that extract() always calls the public endpoint listing. When a specific job ID is in the URL parameters, I should try fetching that single job directly first using a detail API endpoint, then fall back to filtering the listing results if needed.

For UltiPro, I'm looking at the job board structure—the URL contains a company code and board GUID, and there's a corresponding API endpoint that returns paginated job results. I need to determine what fields the API returns to ensure they map correctly to the adapter's normalization logic. I need to handle the Workday CXS API endpoint, which uses a POST request with specific parameters and returns job postings in a different structure with fields like jobPostings, externalPath, and remoteType. I'll build an adapter that handles this response format alongside the UltiPro patterns.

For ADP, the real challenge is that modern WorkForceNow boards use Shadow DOM components that don't expose content through standard page scraping, but the job data is likely embedded in script tags as JSON configuration for the Angular application, so I should look for that encoded data instead of trying to parse the rendered components directly. me add a JSON script fallback in the ADP adapter.

Also, the ADP URL has cid=14fa7571-bfac-427f-aa18-9488391d4c5e. This CID is the company ID. ADP might have a recruitment API at:
https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={cid}&ccId={ccId}&lang={lang}&type=MP

But this would just return the same Angular shell HTML.

Actually, I wonder if ADP has a public JSON API. Based on my research, ADP WorkForceNow does not expose a public unauthenticated job listing API. The rendering relies on the Angular app making authenticated internal API calls.

The best fix for ADP is to improve the readiness detection for when the SPA finishes rendering, use more flexible selectors that work with SDF components in light DOM, and look for jobs embedded in script tags with JSON data. Looking at the rendered page structure, the job listings are wrapped in custom SDF elements with slotted anchor tags that contain the job title and location information, which should be accessible through the page content.

Let me look at the browser fetch and readiness logic more closely.

Read c:\Projects\pre_poc_ai_crawler\backend\app\services\crawl_fetch_runtime.py (lines 101-250)
Grep "readiness|current.openings|SDF|sdf-link|ultipro|workday" (in backend/app/services, type: py)
25 lines of output
Let me search for how resolve_listing_readiness_platform is used in the runtime code.

Grep "resolve_listing_readiness_platform|readiness_platform|wait_for.*selector|networkidle|current.openings" (in backend/app/services/crawl_fetch_runtime.py)
42 lines of output
I can see that the browser fetch waits for networkidle. Now I need to look at how the readiness platform is used. Let me search for it more specifically.

Grep "resolve_listing_readiness|readiness_domains|readiness_path|platform_policy.*browser|requires_browser" (in backend/app/services/crawl_fetch_runtime.py)
11 lines of output
So the requires_browser from platform policy directly controls whether browser fetch is used. ADP has requires_browser: true, so browser should be used.

Now let me look for how readiness_platform is actually used (it might not be used at all in the current code):

Grep "resolve_listing_readiness_platform" (in backend)
23 lines of output
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\config\platform_readiness.py
Globpattern: "backend/app/services/config/platform_readiness.json"
Found 1 file
Read c:\Projects\pre_poc_ai_crawler\backend\app\services\config\platform_readiness.json
Now I have a complete picture. Let me look at how the readiness selectors are used in the browser fetch:

Grep "resolve_listing_readiness_override|readiness_selectors|readiness_override|wait_for_selector" (in backend/app/services/crawl_fetch_runtime.py)
1 line of output
Grep "resolve_listing_readiness_override" (in backend)
11 lines of output
The resolve_listing_readiness_override function is defined but I can't find where it's actually called in the fetch runtime. Let me search for it in the traversal or other files.

Grep "resolve_listing_readiness_override" (in backend)
2 lines of output
The resolve_listing_readiness_override function is only defined but never called anywhere! This is a bug - the readiness selectors for ADP and UltiPro are configured but not actually used.

Now let me look at the browser fetch function to understand where I should hook in the readiness selectors.

The readiness override function is defined but never called anywhere — that's a root cause. Let me read the full browser fetch section to understand where to wire it in.

Read c:\Projects\pre_poc_ai_crawler\backend\app\services\crawl_fetch_runtime.py (lines 501-660)
Now I can see where to wire in the readiness selectors. After the networkidle wait (line 591-599), I can add a call to resolve_listing_readiness_override(url) and then call page.wait_for_selector() for each selector.

Let me now look at the full _fetch_with_browser function to understand its signature and context.

Read c:\Projects\pre_poc_ai_crawler\backend\app\services\crawl_fetch_runtime.py (lines 421-500)
Now I have a complete picture. Let me now build the fix plan and implement all changes:

Changes needed:

_browser_fetch in crawl_fetch_runtime.py: Wire in readiness selectors after networkidle wait

saashr.py: Fix detail mode when ShowJob= param present

adp.py: Improve selectors - add <a slot="default-link"> and JSON script fallback

ultipro.py: Create new adapter for UltiPro/UKG

workday.py: Create new adapter for Workday

registry.py: Register ultipro and workday adapters

platforms.json: Add adapter_names: ["workday"] to workday family, update ultipro key

platform_readiness.json: Add workday readiness selectors

TEST_SITES.md: Add the new URLs

Let me now implement each fix. Starting with the readiness selectors in _browser_fetch - I need to add logic after the networkidle wait that checks for platform-specific readiness conditions before proceeding.

The approach is to fetch the readiness configuration for the URL, then iterate through the available selectors and wait for whichever one appears first. Each selector gets a timeout based on the readiness config, and if none of them match, we continue anyway since this is best-effort.

Fix 2: SaaSHR detail mode
For the ShowJob= parameter in the URL, I need to decide between filtering the listing results or hitting a detail API endpoint directly. The detail endpoint exists but I'm not sure about all its parameters, so I'll start with filtering the listing results. The tricky part is that pagination might mean the specific job isn't in the current results, but if it's a valid job ID in the URL, it should be in the full listing somewhere.

Actually, let me go with the direct single-job endpoint instead—it's cleaner and more reliable. I can fall back to filtering the listing if that doesn't work.

Now for the ADP improvements: the adapter currently uses selectolax to find .current-openings-item elements, but after Angular renders the page, the actual job cards are populated in the DOM. The job titles are wrapped in sdf-link web components...

Checking if selectolax can traverse into the slotted content...

Since Playwright's page.content() returns the light DOM with the slotted <a> element visible inside <sdf-link>, selectolax should be able to find it. The selector [id^='lblTitle_'], sdf-link, a will match the first available element, so if there's no id match, it finds the sdf-link and gets its text content—though I need to verify whether .text() properly extracts text from nested slotted elements.

The real issue with ADP is that I haven't been using the readiness selectors properly. If I wait for .current-openings-item or [id^='lblTitle_'] to appear before extracting the HTML, the content should already be loaded. So the main fixes are wiring up those readiness selectors and adding a[slot="default-link"] as a fallback title selector, plus embedding JSON data as another fallback option.

Now I'm moving on to the UltiPro adapter...

Defining the UltiPro adapter class... Writing the adapter methods... Extracting and normalizing job fields... I'm setting up the Workday adapter class that inherits from BaseAdapter, implementing the platform detection and job extraction methods that will handle Workday job board URLs and HTML content.

Now I'm parsing the URL to extract the tenant identifier and site path, then constructing the API endpoint to fetch jobs from Workday's API with pagination support... Continuing to build the normalization function...

I'm extracting the job details from each item—title, external path, location, posting date, and employment type—then constructing the full job URL by joining the host and site path with the external path, and starting to build the record dictionary with these cleaned values.

Now I'm adding conditional fields to the record based on what data is available, including the job URL, location, posting date, job type, and remote work status if it's not a standard on-site designation. The _clean method just strips and normalizes text values.

Looking at the SaaSHR extraction method...

The issue is that try_public_endpoint fetches all job requisitions from the listing, but when a specific job ID is passed via the ShowJob parameter, we should only extract that single job's details instead of the entire list. I need to detect the presence of that parameter and route to a different extraction path that pulls just that one job record. I think the real issue is that the SaaSHR API's listing endpoint doesn't include the full job description—it only returns basic fields like title and URL. So when the adapter normalizes those rows, it's creating records with empty descriptions because the detail content simply isn't available in the listing response. The user is seeing links without the actual job details because the extraction is pulling from a listing endpoint that doesn't provide that information. I need to verify the adapter factory key matches what's defined in platforms.json, and check how the configured adapter names are being resolved to ensure the SaaSHR adapter gets properly registered.

For Workday, I notice there's no adapter_names field in the platforms.json entry, so I'll need to add that. The can_handle() method relies on detect_platform_family() to identify the platform, and for UltiPro it should recognize the recruiting.ultipro.com domain pattern and return the correct family identifier. Writing the adapter registry...

The ADP adapter should correctly route to listing extraction since the URL has selectedMenuKey=CurrentOpenings. The key fix is ensuring the readiness selector waits for .current-openings-item elements to appear before extracting. For the job title selector, I'm checking the fallback chain: [id^='lblTitle_'] for older layouts, sdf-link for SDF-rendered content, and plain anchors as a last resort.

Since sdf-link is a custom element with slotted light DOM children, the inner <a slot="default-link"> should be accessible to selectolax even though it's distributed into the shadow DOM—the element itself stays in the light DOM. Once the page fully renders and readiness selectors are properly wired, the title extraction should work. Now let me think through the Atlas M adapter.

Atlas MedStaff is a custom site with an unknown ATS, and its job search at /job-search/ is likely JS-rendered. The URL pattern matches generic_jobs in the token list, but that family doesn't require browser rendering by default. Adding it as a site-specific exception violates the no-hacks rule, and making all generic_jobs sites browser-dependent would be too broad. The real issue is that resolve_platform_runtime_policy returns requires_browser: False for this family when it probably should be True.

The user would need to enable advanced_enabled: true in their crawl settings to trigger browser rendering for this site. Without inspecting Atlas MedStaff's actual HTML, I can't determine if they use a known ATS like Bullhorn or JobDiva. I'll focus on the four definitive fixes and note that Atlas MedStaff requires browser mode as a configuration workaround.

Now I'm checking the function signature for the browser fetch handler...

Adding the readiness selector wait after the networkidle timeout check, before the expansion diagnostics initialization. I need to import the readiness resolver and wire it into the right location in the code.

Looking at how the adapter factory registration works with the configured adapter names from platforms.json... I see that configured_adapter_names() pulls the adapter names from platforms.json, and each one needs a corresponding factory in _ADAPTER_FACTORIES. Since ultipro_ukg is configured but missing from the factories dict, it's being logged as unknown. I need to add both UltiProAdapter and WorkdayAdapter to the factories, update platforms.json with the workday adapter name, and check whether Workday needs the try_public_endpoint method that the recovery logic looks for.

The Workday adapter handles recovery through its CXS API POST mechanism, so I don't need to add try_public_endpoint there. Now I'm ready to implement all the changes: updating the fetch runtime with a readiness selector wait, fixing detail mode detection in the SaaSHR adapter, adding a fallback selector in ADP, and creating the new UltiPro and Workday adapter files.

After that, I need to register both new adapters in the registry, update the platforms configuration to include Workday, add the readiness selectors to the platform readiness config, and document the test sites. For the Workday API URL parsing, I'm extracting the tenant identifier from the domain structure—pulling it from the netloc before the .wd5.myworkdayjobs.com portion. Building URL construction logic... Now I'm ready to implement this—I'll use ToolSearch to retrieve TodoWrite and start tracking the work.