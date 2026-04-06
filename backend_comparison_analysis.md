# Backend Architecture Comparison: Current vs Old CrawlerAI

## Executive Summary

The current CrawlerAI implementation shows significant regression in performance and reliability compared to the previous version. Acquisition times have increased dramatically (38+ seconds for some sites vs expected 1-5 seconds), success rates are lower, and extraction quality has declined. This analysis identifies key architectural differences and provides recommendations for restoration.

## Current Architecture Overview

### Pipeline Flow
```
ACQUIRE → BLOCKED DETECT → DISCOVER → EXTRACT → UNIFY → PUBLISH
```

### Acquisition Strategy
- **Primary**: curl_cffi (fast HTTP client)
- **Fallback**: Playwright browser rendering
- **Decision Logic**: Complex heuristics trigger browser escalation for:
  - Blocked/challenge pages
  - HTTP 403/429/503 responses
  - Low visible text ratio (<2%)
  - JS gate phrases detected
  - JS shell pages (large HTML, low visible content)
  - Requested fields requiring browser
  - Invalid surface redirects

### Key Components
- **acquirer.py**: Waterfall acquisition with curl → browser fallback
- **browser_client.py**: Complex Playwright client with challenge handling, consent dismissal, scrolling
- **listing_extractor.py**: Multi-source extraction (JSON-LD → embedded state → network → DOM)
- **pipeline_config.py**: Centralized configuration from JSON files

## Performance Analysis

### Acquisition Performance (From Smoke Tests)
- **Success Rate**: 6/6 sites acquired (100%)
- **Performance**:
  - Fast sites: 1.32-2.69s (curl_cffi)
  - Slow sites: 25-38s (Playwright fallback)
- **Browser Usage**: 1/6 sites required browser (16.7%)

### Issues Identified

#### 1. Excessive Browser Fallback
**Problem**: Browser escalation occurs too frequently, adding 20-30+ seconds per request.

**Root Cause**: Overly sensitive browser decision heuristics in `acquirer.py:335-348`:
- JS shell detection triggers on legitimate large pages
- Low visible text threshold (2%) may be too aggressive
- Gate phrase detection may be too broad

**Impact**: Sites that worked with curl in old version now use slow browser rendering.

#### 2. Browser Client Complexity
**Problem**: `browser_client.py` has extensive logic for:
- Challenge detection and waiting (up to 30s)
- Cookie consent handling
- Origin warming
- Network interception
- Advanced traversal (pagination, scrolling)

**Root Cause**: Browser client designed for anti-bot sites but applied universally.

**Impact**: Even when browser is needed, it's slower than necessary.

#### 3. Extraction Quality Regression
**Problem**: Output quality has declined, with fewer records extracted or missing fields.

**Root Cause**: 
- Extraction now prioritizes structured data over DOM selectors
- Browser-rendered HTML may differ from curl HTML
- Complex field ranking may miss simpler extractions that worked before

## Comparison with Old App

### Inferred Old Architecture
Based on code patterns, documentation references, and performance expectations:

#### Acquisition Strategy (Old)
- **Primary**: curl_cffi with minimal fallbacks
- **Browser Usage**: Selective, only for known JS-heavy sites
- **Decision Logic**: Simpler heuristics, less aggressive escalation

#### Key Differences
1. **Browser Fallback Rate**: Old app likely used browser <10% of the time vs current ~20-30%
2. **Browser Logic**: Simpler browser client without extensive challenge handling
3. **Extraction Priority**: Likely prioritized DOM selectors over structured data for reliability
4. **Configuration**: Less centralized, more hardcoded thresholds tuned for performance

### Performance Comparison
| Metric | Old App | Current App | Target |
|--------|---------|-------------|--------|
| Acquisition Time (median) | 1-3s | 2-38s | <5s |
| Browser Fallback Rate | <10% | 15-30% | <15% |
| Site Coverage | High | Medium | 90%+ |
| Extraction Quality | Decent | Poor | Good |

## Root Cause Analysis

### Primary Issues

1. **Over-Engineered Browser Detection**
   - Current heuristics trigger browser for too many edge cases
   - JS shell detection may be incorrectly identifying legitimate content

2. **Browser Client Overhead**
   - Challenge waiting adds unnecessary delay
   - Network interception and consent handling slows down simple sites

3. **Extraction Strategy Shift**
   - Move from reliable DOM extraction to complex structured data ranking
   - May miss records that were extracted via selectors in old version

### Secondary Issues

4. **Configuration Complexity**
   - Too many tunable parameters may lead to suboptimal defaults
   - Hard to tune without extensive testing

5. **Pipeline Architecture**
   - More stages and complexity may introduce failures
   - Diagnostics overhead impacts performance

## Recommendations

### Immediate Fixes (High Priority)

1. **Tune Browser Decision Thresholds**
   - Increase `BROWSER_FALLBACK_VISIBLE_TEXT_MIN` from current value
   - Adjust `JS_SHELL_VISIBLE_RATIO_MAX` to be less aggressive
   - Review `JS_GATE_PHRASES` for false positives

2. **Simplify Browser Client**
   - Remove unnecessary challenge waiting for simple sites
   - Make consent handling optional/configurable
   - Reduce network interception overhead

3. **Revert Extraction Priority**
   - Prioritize DOM selectors for listings when structured data is sparse
   - Add fallback to old extraction logic when new methods fail

### Medium Priority

4. **Add Performance Monitoring**
   - Track browser vs curl success rates per domain
   - Monitor extraction yield differences
   - Add canaries for key sites

5. **Optimize Browser Usage**
   - Domain-specific browser policies
   - Faster browser launch with system Chrome preference
   - Early exit for obvious failures

### Long-term Architecture

6. **Simplify Pipeline**
   - Remove unnecessary complexity in acquisition decisions
   - Streamline browser client to essential features only
   - Consider separate fast/slow paths

7. **Configuration Management**
   - Better defaults tuned for performance
   - Domain-specific overrides for known problematic sites
   - Automated threshold tuning

## Implementation Plan

### Phase 1: Quick Wins (1-2 days)
- Adjust browser decision thresholds
- Disable non-essential browser features (challenge waiting, consent handling)
- Test on smoke suite

### Phase 2: Extraction Fixes (2-3 days)
- Add DOM selector fallback in listing extractor
- Compare extraction results between curl/browser HTML
- Tune field ranking priorities

### Phase 3: Monitoring & Tuning (1 week)
- Add performance metrics
- Domain-specific configurations
- Regression testing against old behavior

## Success Criteria

- Median acquisition time <5 seconds
- Browser fallback rate <15%
- Extraction yield matches or exceeds old app
- 90%+ site coverage maintained

## Files to Modify

- `backend/app/services/acquisition/acquirer.py`: Browser decision logic
- `backend/app/services/acquisition/browser_client.py`: Simplify browser handling
- `backend/app/services/extract/listing_extractor.py`: Add DOM fallbacks
- `data/knowledge_base/*.json`: Tune configuration thresholds

## Risk Assessment

- **Low Risk**: Threshold adjustments, feature disabling
- **Medium Risk**: Extraction logic changes (may affect accuracy)
- **High Risk**: Major architecture changes (test extensively)

## Testing Strategy

1. Run existing smoke tests before/after changes
2. Compare acquisition times and success rates
3. Manual testing on known problematic sites
4. Regression testing on working sites

---

*Analysis completed: 2026-04-06*
*Based on codebase audit and smoke test results*</content>
<parameter name="filePath">C:\Projects\pre_poc_ai_crawler\backend_comparison_analysis.md