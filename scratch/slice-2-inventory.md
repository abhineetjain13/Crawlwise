# Slice 2 Inventory

Inventory captured before consolidation. File:line references are from the current checkout after the move targets were identified.

| Current file : line | Current name | New name / target | Target file : section |
|---|---|---|---|
| `backend/app/services/extract/noise_policy.py:50` | `LOW_QUALITY_MERGE_TOKENS` | same | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:22` | `TITLE_NOISE_WORDS` | same | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:80` | `_COMMON_DETAIL_REJECT_PHRASES` | `FIELD_POLLUTION_RULES["__common__"]` | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:81` | `_DETAIL_FIELD_REJECT_PHRASES` | `FIELD_POLLUTION_RULES[field]` | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:39` | `_NETWORK_PAYLOAD_NOISE_URL_RE` pattern payload | `NETWORK_PAYLOAD_NOISE_URL_PATTERN` | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:113` | `_NOISY_PRODUCT_ATTRIBUTE_KEYS` | `NOISY_PRODUCT_ATTRIBUTE_KEYS` | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:120` | `_NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES` | `NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES` | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:122` | `_NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS` | `NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS` | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:39` and `backend/app/services/config/extraction_rules.py:1490` | `_CSS_NOISE_VALUE_RE` + split CSS token tables | `CSS_NOISE_TOKENS`, `CSS_NOISE_PATTERN` | `backend/app/services/config/extraction_rules.py` : noise consolidation block |
| `backend/app/services/extract/noise_policy.py:214` | `_NOISE_CONTAINER_TOKENS` | `NOISE_CONTAINER_TOKENS` | `backend/app/services/config/extraction_rules.py` : semantic/noise container section |
| `backend/app/services/extract/noise_policy.py:256` | `_SOCIAL_HOST_SUFFIXES` | `SOCIAL_HOST_SUFFIXES` | `backend/app/services/config/extraction_rules.py` : semantic/noise container section |
| `backend/app/services/extract/noise_policy.py:261` | `_NOISE_CONTAINER_REMOVAL_SELECTOR` | `NOISE_CONTAINER_REMOVAL_SELECTOR` | `backend/app/services/config/extraction_rules.py` : semantic/noise container section |
| `backend/app/services/extract/noise_policy.py:129` | `SECTION_LABEL_SKIP_TOKENS` | `SEMANTIC_SECTION_NOISE["label_skip_tokens"]` | `backend/app/services/config/extraction_rules.py` : `SEMANTIC_SECTION_NOISE` |
| `backend/app/services/extract/noise_policy.py:139` | `SECTION_KEY_SKIP_PREFIXES` | `SEMANTIC_SECTION_NOISE["key_skip_prefixes"]` | `backend/app/services/config/extraction_rules.py` : `SEMANTIC_SECTION_NOISE` |
| `backend/app/services/extract/noise_policy.py:149` | `SECTION_BODY_SKIP_PHRASES` | `SEMANTIC_SECTION_NOISE["body_skip_phrases"]` | `backend/app/services/config/extraction_rules.py` : `SEMANTIC_SECTION_NOISE` |

Notes:
- `SECTION_SKIP_PATTERNS`, `SECTION_ANCESTOR_STOP_TAGS`, and `SECTION_ANCESTOR_STOP_TOKENS` already lived in config; Slice 2 folds the sibling section-noise tables under the new `SEMANTIC_SECTION_NOISE` dict.
- `CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS`, `CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN`, and `CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN` were already in config and remain there.
