Analysis of Major Duplicate Code Groups: Repository abhineetjain13/Crawlwise

1. Analysis Summary and Redundancy Metrics

A comprehensive technical debt audit of the abhineetjain13/Crawlwise repository has identified a systemic reliance on "Copy-Paste" development patterns that significantly compromise the project's long-term maintainability. Out of 69,504 lines analyzed, 5,185 lines are flagged as redundant, resulting in a duplication density of approximately 7.46%.

This volume of redundancy is concentrated across 103 distinct duplicate groups, which are categorized by impact as follows:

* Major Duplicate Groups: 33
* Minor Duplicate Groups: 70

From an architectural perspective, this duplication rate is unacceptable. It indicates that code is being propagated without regard for abstraction, creating a massive surface area for "logic drift" where a single bug must be fixed in multiple locations. The prevalence of Major severity issues in core API clients and test suites suggests an immediate risk to developer agility and CI efficiency.

2. Detailed Catalog of Major Duplicate Groups

The following catalog provides the technical specifics for every "Major" severity duplicate block identified. These must be prioritized for consolidation.

Duplicate Group 1

Metric	Value
Total Lines Involved	67 lines
Files Affected	1 distinct path (3 instances)

* frontend/lib/api/client.ts [281:302]
* frontend/lib/api/client.ts [216:237]
* frontend/lib/api/client.ts [151:173]

Duplicate Group 2

Metric	Value
Total Lines Involved	45 lines
Files Affected	1 distinct path (3 instances)

* frontend/lib/api/client.ts [262:276]
* frontend/lib/api/client.ts [116:130]
* frontend/lib/api/client.ts [197:211]

Duplicate Group 3

Metric	Value
Total Lines Involved	42 lines
Files Affected	1 distinct path (3 instances)

* frontend/lib/api/client.ts [249:262]
* frontend/lib/api/client.ts [184:197]
* frontend/lib/api/client.ts [102:115]

Duplicate Group 4

Metric	Value
Total Lines Involved	62 lines
Files Affected	1 distinct path (2 instances)

* frontend/lib/api/client.ts [181:211]
* frontend/lib/api/client.ts [246:276]

Duplicate Group 7

Metric	Value
Total Lines Involved	106 lines
Files Affected	2 distinct paths

* backend/app/services/acquisition/acquirer.py [2036:2088]
* backend/app/services/llm_integration/page_classifier.py [56:108]

Duplicate Group 8

Metric	Value
Total Lines Involved	155 lines
Files Affected	3 distinct paths

* backend/app/services/crawl_events.py [285:336]
* backend/app/models/crawl.py [111:161]
* backend/app/services/_batch_progress.py [162:213]

Duplicate Group 11

Metric	Value
Total Lines Involved	55 lines
Files Affected	2 distinct paths

* backend/app/services/pipeline/core.py [1760:1787]
* backend/app/services/crawl_metadata.py [72:98]

Duplicate Group 13

Metric	Value
Total Lines Involved	260 lines
Files Affected	2 distinct paths

* backend/tests/services/test_crawl_service.py [767:862]
* backend/tests/services/extract/test_listing_extractor.py [175:338]

Duplicate Group 21

Metric	Value
Total Lines Involved	91 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/test_crawl_service.py [1375:1421]
* backend/tests/services/test_crawl_service.py [1326:1369]

Duplicate Group 38

Metric	Value
Total Lines Involved	65 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/test_crawl_service.py [1687:1729]
* backend/tests/services/test_crawl_service.py [537:558]

Duplicate Group 39

Metric	Value
Total Lines Involved	56 lines
Files Affected	1 distinct path (4 instances)

* backend/tests/services/acquisition/test_fragment_capture.py [313:326]
* backend/tests/services/acquisition/test_fragment_capture.py [138:151]
* backend/tests/services/acquisition/test_fragment_capture.py [261:274]
* backend/tests/services/acquisition/test_fragment_capture.py [200:213]

Duplicate Group 44

Metric	Value
Total Lines Involved	114 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/adapters/test_adapters.py [472:536]
* backend/tests/services/adapters/test_adapters.py [551:599]

Duplicate Group 45

Metric	Value
Total Lines Involved	75 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/adapters/test_adapters.py [550:598]
* backend/tests/services/adapters/test_adapters.py [428:453]

Duplicate Group 54

Metric	Value
Total Lines Involved	42 lines
Files Affected	1 distinct path (3 instances)

* backend/tests/services/extract/test_signal_inventory.py [180:193]
* backend/tests/services/extract/test_signal_inventory.py [159:172]
* backend/tests/services/extract/test_signal_inventory.py [243:256]

Duplicate Group 60

Metric	Value
Total Lines Involved	159 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/adapters/test_adapters.py [560:619]
* backend/tests/services/adapters/test_adapters.py [604:702]

Duplicate Group 61

Metric	Value
Total Lines Involved	89 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/adapters/test_adapters.py [429:453]
* backend/tests/services/adapters/test_adapters.py [472:535]

Duplicate Group 66

Metric	Value
Total Lines Involved	285 lines
Files Affected	2 distinct paths

* backend/tests/services/test_crawl_service.py [1610:1623]
* backend/tests/services/extract/test_listing_extractor.py [849:1119]

Duplicate Group 69

Metric	Value
Total Lines Involved	94 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/acquisition/test_acquirer.py [319:365]
* backend/tests/services/acquisition/test_acquirer.py [365:411]

Duplicate Group 70

Metric	Value
Total Lines Involved	94 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/acquisition/test_acquirer.py [322:368]
* backend/tests/services/acquisition/test_acquirer.py [278:319]

Duplicate Group 73

Metric	Value
Total Lines Involved	36 lines
Files Affected	1 distinct path (3 instances)

* backend/app/api/crawls.py [261:272]
* backend/app/api/crawls.py [359:370]
* backend/app/api/crawls.py [329:340]

Duplicate Group 75

Metric	Value
Total Lines Involved	37 lines
Files Affected	1 distinct path (3 instances)

* backend/app/services/acquisition/acquirer.py [869:880]
* backend/app/services/acquisition/acquirer.py [1017:1029]
* backend/app/services/acquisition/acquirer.py [804:815]

Duplicate Group 79

Metric	Value
Total Lines Involved	48 lines
Files Affected	1 distinct path (4 instances)

* backend/tests/api/test_records_exports.py [353:364]
* backend/tests/api/test_records_exports.py [536:547]
* backend/tests/api/test_records_exports.py [487:498]
* backend/tests/api/test_records_exports.py [398:409]

Duplicate Group 80

Metric	Value
Total Lines Involved	72 lines
Files Affected	1 distinct path (6 instances)

* backend/tests/api/test_records_exports.py [266:277]
* backend/tests/api/test_records_exports.py [533:544]
* backend/tests/api/test_records_exports.py [122:133]
* backend/tests/api/test_records_exports.py [45:56]
* backend/tests/api/test_records_exports.py [83:94]
* backend/tests/api/test_records_exports.py [161:172]

Duplicate Group 81

Metric	Value
Total Lines Involved	107 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/test_crawl_service.py [875:942]
* backend/tests/services/test_crawl_service.py [1685:1723]

Duplicate Group 82

Metric	Value
Total Lines Involved	236 lines
Files Affected	2 distinct paths

* backend/tests/services/test_crawl_service.py [802:862]
* backend/tests/services/test_crawl_service.py [868:934]
* backend/tests/services/extract/test_listing_extractor.py [231:338]

Duplicate Group 85

Metric	Value
Total Lines Involved	48 lines
Files Affected	1 distinct path (3 instances)

* backend/tests/services/acquisition/test_fragment_capture.py [259:274]
* backend/tests/services/acquisition/test_fragment_capture.py [198:213]
* backend/tests/services/acquisition/test_fragment_capture.py [311:326]

Duplicate Group 86

Metric	Value
Total Lines Involved	53 lines
Files Affected	1 distinct path (2 instances)

* backend/tests/services/acquisition/test_fragment_capture.py [259:277]
* backend/tests/services/acquisition/test_fragment_capture.py [198:217]

Duplicate Group 99

Metric	Value
Total Lines Involved	42 lines
Files Affected	1 distinct path (3 instances)

* backend/tests/services/test_llm_runtime.py [102:115]
* backend/tests/services/test_llm_runtime.py [62:75]
* backend/tests/services/test_llm_runtime.py [403:416]

3. Primary Redundancy Hotspots

The following files represent the most significant sources of code debt in the repository. Refactoring efforts must prioritize these files to yield the highest impact:

Critical Targets (High Frequency)

* frontend/lib/api/client.ts: Central to Groups 1, 2, 3, and 4. This file is a major offender, repeatedly implementing similar API communication patterns.
* backend/tests/services/test_crawl_service.py: Involved in Groups 13, 21, 38, 66, 81, and 82. This is the primary redundancy hotspot in the backend test suite.

Secondary Targets

* backend/tests/services/extract/test_listing_extractor.py: Critical participant in heavy-weight Groups 13, 66, and 82.
* backend/tests/services/adapters/test_adapters.py: Plagued by repetitive setup in Groups 44, 45, 60, and 61.
* backend/tests/api/test_records_exports.py: Redundant logic found in Groups 79 and 80.
* backend/tests/services/acquisition/test_fragment_capture.py: Redundancy observed in Groups 39, 85, and 86.

4. Strategic Recommendations for Logic Consolidation

To mitigate the architectural risk identified in this report, I mandate the following actions:

Command 1: Mandate the abstraction of frontend API communication patterns. The repetitive blocks in frontend/lib/api/client.ts (Groups 1–4) must be unified into a generalized request handler. Furthermore, these blocks frequently contain the "Unexpected await inside a loop" critical antipattern (as seen on lines 107, 125, 140, 149, etc.). Refactoring this code is not merely about removing duplicates; it is about replacing inefficient, sequential I/O with modern concurrent patterns.

Command 2: Mandate the creation of shared test utilities and fixtures. The massive duplication in backend service tests—specifically Groups 13 (260 lines), 66 (285 lines), and 82 (236 lines)—is indicative of bloated test setups. The development team must extract common assertions and mocking logic into a dedicated test utility library or pytest fixtures. Addressing Groups 13 and 82 alone will remove nearly 500 lines of redundant code from the repository.

Command 3: Mandate a review and unification of core acquisition and classification logic. The 106-line duplication shared between backend/app/services/acquisition/acquirer.py and backend/app/services/llm_integration/page_classifier.py (Group 7) represents a high-risk drift scenario. Common logic for page analysis and element identification must be moved to a shared service layer to ensure consistent behavior across the acquisition and classification pipelines.
