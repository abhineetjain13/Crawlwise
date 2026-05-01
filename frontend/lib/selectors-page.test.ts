import { describe, expect, it } from 'vitest';
import {
  buildXPathForElement,
  inferSelectorSurface,
  mergeSelectorRows,
  selectRelevantSelectorRecords,
  xpathLiteral,
} from '../app/selectors/page';

describe('selectors page helpers', () => {
  it('infers job detail when fields or URL are job-oriented', () => {
    expect(inferSelectorSurface(['company', 'location'], 'https://example.com/jobs/123')).toBe(
      'job_detail',
    );
    expect(inferSelectorSurface(['price'], 'https://example.com/products/widget')).toBe(
      'ecommerce_detail',
    );
  });

  it('prefers exact-surface selector records over generic fallbacks', () => {
    const records = selectRelevantSelectorRecords(
      [
        {
          id: 2,
          domain: 'example.com',
          surface: 'generic',
          field_name: 'price',
          css_selector: '.generic-price',
          xpath: null,
          regex: null,
          status: 'validated',
          sample_value: '$19.99',
          source: 'domain_memory',
          source_run_id: null,
          is_active: true,
          created_at: '',
          updated_at: '',
        },
        {
          id: 1,
          domain: 'example.com',
          surface: 'ecommerce_detail',
          field_name: 'price',
          css_selector: '.detail-price',
          xpath: null,
          regex: null,
          status: 'validated',
          sample_value: '$19.99',
          source: 'domain_memory',
          source_run_id: null,
          is_active: true,
          created_at: '',
          updated_at: '',
        },
        {
          id: 3,
          domain: 'example.com',
          surface: 'ecommerce_detail',
          field_name: 'title',
          css_selector: 'h1',
          xpath: null,
          regex: null,
          status: 'validated',
          sample_value: 'Widget Prime',
          source: 'domain_memory',
          source_run_id: null,
          is_active: false,
          created_at: '',
          updated_at: '',
        },
      ],
      'ecommerce_detail',
    );

    expect(
      records.map((record) => `${record.surface}:${record.field_name}:${record.css_selector}`),
    ).toEqual(['ecommerce_detail:price:.detail-price', 'generic:price:.generic-price']);
  });

  it('keeps saved selector values when expected-column rows are merged in', () => {
    const merged = mergeSelectorRows(
      [
        {
          key: 'saved-price',
          selectorId: 12,
          surface: 'ecommerce_detail',
          fieldName: 'price',
          kind: 'xpath',
          selectorValue: "//span[@class='price']",
          extractedValue: '$19.99',
          source: 'domain_memory',
          state: 'saved',
        },
      ],
      [
        {
          key: 'blank-price',
          selectorId: null,
          surface: null,
          fieldName: 'price',
          kind: 'xpath',
          selectorValue: '',
          extractedValue: '',
          source: 'manual',
          state: 'idle',
        },
      ],
    );

    expect(merged).toHaveLength(1);
    expect(merged[0]?.selectorId).toBe(12);
    expect(merged[0]?.selectorValue).toBe("//span[@class='price']");
    expect(merged[0]?.state).toBe('saved');
  });

  it('lets generated suggestions replace stale saved selector values when requested', () => {
    const merged = mergeSelectorRows(
      [
        {
          key: 'saved-price',
          selectorId: 12,
          surface: 'ecommerce_listing',
          fieldName: 'price',
          kind: 'xpath',
          selectorValue: "//ul/li[1]//span[@class='price']",
          extractedValue: '$19.99',
          source: 'domain_memory',
          state: 'saved',
        },
      ],
      [
        {
          key: 'generated-price',
          selectorId: null,
          surface: 'ecommerce_listing',
          fieldName: 'price',
          kind: 'css_selector',
          selectorValue: '.ProductCardBody-price',
          extractedValue: '$24.00',
          source: 'llm_xpath',
          state: 'accepted',
        },
      ],
      { preferIncoming: true },
    );

    expect(merged).toHaveLength(1);
    expect(merged[0]?.selectorId).toBe(12);
    expect(merged[0]?.selectorValue).toBe('.ProductCardBody-price');
    expect(merged[0]?.kind).toBe('css_selector');
    expect(merged[0]?.state).toBe('accepted');
  });

  it('builds a unique XPath from the loaded preview DOM', () => {
    document.body.innerHTML = `
<main>
<section class="product-gallery">
 <button aria-label="Black" data-testid="color-swatch"> </button>
</section>
</main>
`;

    const element = document.querySelector("[data-testid='color-swatch']");
    expect(element).not.toBeNull();

    const xpath = buildXPathForElement(element!);
    const result = document.evaluate(
      xpath,
      document,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null,
    );

    expect(result.snapshotLength).toBe(1);
    expect(xpath).toContain('@data-testid');
  });

  it('builds a valid XPath literal when the value contains both quote types', () => {
    const literal = xpathLiteral(`it's"cool"`);

    expect(literal).toBe(`concat('it',"'",'s"cool"')`);
    expect(
      document.evaluate(`string(${literal})`, document, null, XPathResult.STRING_TYPE, null)
        .stringValue,
    ).toBe(`it's"cool"`);
  });
});
