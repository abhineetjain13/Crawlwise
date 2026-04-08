import { describe, expect, it } from "vitest";

import type { CrawlRecord } from "../../lib/api/types";
import { estimateDataQuality, validateAdditionalFieldName } from "./shared";

function makeRecord(id: number, data: Record<string, unknown>): CrawlRecord {
  return {
    id,
    run_id: 1,
    source_url: `https://example.com/${id}`,
    data,
    raw_data: {},
    discovered_data: {},
    source_trace: {},
    raw_html_path: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("estimateDataQuality", () => {
  it("returns unknown when there is no record data", () => {
    const quality = estimateDataQuality([], ["title", "price"]);

    expect(quality.level).toBe("unknown");
    expect(quality.score).toBe(0);
  });

  it("returns high for dense, well-shaped rows", () => {
    const records = [
      makeRecord(1, { title: "A", price: "$10", brand: "X" }),
      makeRecord(2, { title: "B", price: "$20", brand: "Y" }),
      makeRecord(3, { title: "C", price: "$30", brand: "Z" }),
    ];

    const quality = estimateDataQuality(records, ["title", "price", "brand"]);

    expect(quality.level).toBe("high");
    expect(quality.score).toBeGreaterThanOrEqual(0.75);
  });

  it("returns low for sparse rows", () => {
    const records = [
      makeRecord(1, { title: "A", price: "" }),
      makeRecord(2, { title: "", price: "" }),
      makeRecord(3, { title: "", price: "" }),
    ];

    const quality = estimateDataQuality(records, ["title", "price"]);

    expect(quality.level).toBe("low");
    expect(quality.score).toBeLessThan(0.45);
  });
});

describe("validateAdditionalFieldName", () => {
  it("rejects schema type names", () => {
    expect(validateAdditionalFieldName("AggregateRating")).toContain("schema type");
    expect(validateAdditionalFieldName("breadcrumblist")).toContain("schema type");
  });

  it("rejects day-of-week labels", () => {
    expect(validateAdditionalFieldName("Monday")).toContain("day label");
    expect(validateAdditionalFieldName("sunday")).toContain("day label");
  });

  it("accepts concise business field names", () => {
    expect(validateAdditionalFieldName("supplier_color")).toBeNull();
    expect(validateAdditionalFieldName("material")).toBeNull();
  });
});
