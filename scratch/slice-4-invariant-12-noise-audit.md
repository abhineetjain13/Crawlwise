| Rule set | Token / phrase | Rejects a value that is… | Page-native? | Decision |
|----------|----------------|--------------------------|--------------|----------|
| `FIELD_POLLUTION_RULES["size"]` | `select size` | a variant-picker label rendered in the product UI | Yes | Preserve as page-native label at the noise boundary; do not drop as field pollution |
| `FIELD_POLLUTION_RULES["size"]` | `choose size` | a variant-picker label rendered in the product UI | Yes | Preserve as page-native label at the noise boundary; do not drop as field pollution |
| `FIELD_POLLUTION_RULES["color"]` | `select color` | a variant-picker label rendered in the product UI | Yes | Preserve as page-native label at the noise boundary; do not drop as field pollution |
| `FIELD_POLLUTION_RULES["color"]` | `select colour` | a variant-picker label rendered in the product UI | Yes | Preserve as page-native label at the noise boundary; do not drop as field pollution |
| `TITLE_NOISE_WORDS` / availability normalizer boundary | `availability` | a field label rendered by the page | Yes | Preserve in the `availability` field; continue rejecting title noise elsewhere |
| `FIELD_POLLUTION_RULES["availability"]` | `add to cart` | CTA chrome, not a field label | No | Keep rule unchanged |
| `FIELD_POLLUTION_RULES["__common__"]` | `cookie` | consent/footer chrome | No | Keep rule unchanged |
| `NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES` | `check availability in store` | retail CTA / store helper copy | No | Keep rule unchanged |
| `CSS_NOISE_PATTERN` | `padding` / `margin` / `display` | CSS declaration fragments | No | Keep rule unchanged |
| `CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS` | `footer` / `privacy` / `account` | chrome or policy keys, not product attributes | No | Keep rule unchanged |
| `SECTION_ANCESTOR_STOP_TAGS` | `footer`, `nav`, `header`, `aside` | chrome containers, not content sections | No | Keep rule unchanged |
