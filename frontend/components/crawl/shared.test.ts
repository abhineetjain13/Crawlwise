import { describe, expect, it } from"vitest";

import type { CrawlRecord } from"../../lib/api/types";
import {
 buildLogSiteGroups,
 decodeUrlsForDisplay,
 estimateDataQuality,
 formatCellDisplay,
 getLogStage,
 scoreFieldQuality,
 scoreRecordQuality,
 validateAdditionalFieldName,
} from"./shared";

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
 created_at:"2026-01-01T00:00:00Z",
 };
}

function makeLog(id: number, message: string, level = "info") {
 return {
 id,
 level,
 message,
 created_at:"2026-01-01T00:00:00Z",
 };
}

describe("estimateDataQuality", () => {
 it("returns unknown when there is no record data", () => {
 const quality = estimateDataQuality([], ["title","price"]);

 expect(quality.level).toBe("unknown");
 expect(quality.score).toBe(0);
 });

 it("returns high for dense, well-shaped rows", () => {
 const records = [
 makeRecord(1, { title:"Trail Shoe", price:"$10", brand:"Puma"}),
 makeRecord(2, { title:"Running Tee", price:"$20", brand:"Nike"}),
 makeRecord(3, { title:"Gym Shorts", price:"$30", brand:"Adidas"}),
 ];

 const quality = estimateDataQuality(records, ["title","price","brand"]);

 expect(quality.level).toBe("high");
 expect(quality.score).toBeGreaterThanOrEqual(0.8);
 });

 it("returns low for sparse rows", () => {
 const records = [
 makeRecord(1, { title:"Trail Shoe", price:""}),
 makeRecord(2, { title:"", price:""}),
 makeRecord(3, { title:"", price:""}),
 ];

 const quality = estimateDataQuality(records, ["title","price"]);

 expect(quality.level).toBe("low");
 expect(quality.score).toBeLessThan(0.5);
 });

 it("returns medium for rows that are usable but sparse", () => {
 const records = [
 makeRecord(1, { title:"Trail Shoe", url:"https://example.com/a"}),
 makeRecord(2, { title:"Running Tee", url:"https://example.com/b"}),
 makeRecord(3, { title:"Gym Shorts", url:"https://example.com/c"}),
 ];

 const quality = estimateDataQuality(records, ["title","url","price","brand"]);

 expect(quality.level).toBe("medium");
 expect(quality.score).toBeGreaterThanOrEqual(0.5);
 expect(quality.score).toBeLessThan(0.8);
 });
});

describe("scoreRecordQuality", () => {
 it("penalizes rows with only a single weak field", () => {
 const score = scoreRecordQuality(makeRecord(1, { title:"A"}), ["title","price","brand"]);

 expect(score).toBeLessThan(0.5);
 });

 it("rewards rows with multiple informative fields", () => {
 const score = scoreRecordQuality(
 makeRecord(1, { title:"Trail Shoe", price:"$120", brand:"Puma", url:"https://example.com/p/1"}),
 ["title","price","brand","url"],
 );

 expect(score).toBeGreaterThanOrEqual(0.8);
 });
});

describe("scoreFieldQuality", () => {
 it("tracks field usefulness without a placeholder state", () => {
 const records = [
 makeRecord(1, { material:"Mesh"}),
 makeRecord(2, { material:"Leather"}),
 makeRecord(3, { material:""}),
 ];

 const score = scoreFieldQuality(records,"material");

 expect(score).toBeGreaterThanOrEqual(0.5);
 expect(score).toBeLessThan(0.8);
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

describe("formatCellDisplay", () => {
 it("decodes internationalized product URLs for UI display only", () => {
 expect(
 formatCellDisplay("https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3"),
 ).toBe("https://www.shop.ving.run/product/สีดำ");
 });
});

describe("decodeUrlsForDisplay", () => {
 it("decodes URL strings nested inside preview JSON objects", () => {
 expect(
 decodeUrlsForDisplay({
 url:"https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3",
 images: ["https://cdn.example.com/a.jpg"],
 }),
 ).toEqual({
 url:"https://www.shop.ving.run/product/สีดำ",
 images: ["https://cdn.example.com/a.jpg"],
 });
 });
});

describe("getLogStage", () => {
 it("keeps normalize and persistence distinct from extraction", () => {
 expect(getLogStage("Extracted 1 records using nike adapter")).toBe("extraction");
 expect(getLogStage("Normalized 1 record(s) for persistence")).toBe("normalize");
 expect(getLogStage("Persisted 1 record(s) for https://example.com/p/1")).toBe("persistence");
 });
});

describe("buildLogSiteGroups", () => {
 it("groups logs per site and assigns fixed stages", () => {
 const records = [
 makeRecord(1, { title:"Trail Shoe", url:"https://example.com/p/1" }),
 makeRecord(2, { title:"Road Shoe", url:"https://example.com/p/2" }),
 ];
 const logs = [
 makeLog(1,"Starting crawl run for https://example.com/p/1 (1/2)"),
 makeLog(2,"Acquiring https://example.com/p/1"),
 makeLog(3,"Extracted 1 records using generic extraction path"),
 makeLog(4,"Normalized 1 record(s) for persistence"),
 makeLog(5,"Persisted 1 record(s) for https://example.com/p/1"),
 makeLog(6,"Starting crawl run for https://example.com/p/2 (2/2)"),
 makeLog(7,"Acquiring https://example.com/p/2"),
 makeLog(8,"Extraction yielded 0 records (generic extraction path)","warning"),
 ];

 const groups = buildLogSiteGroups(logs, records);

 expect(groups).toHaveLength(2);
 expect(groups[0].url).toBe("https://example.com/p/1");
 expect(groups[0].stageLogs.acquisition).toHaveLength(1);
 expect(groups[0].stageLogs.extraction).toHaveLength(1);
 expect(groups[0].stageLogs.normalize).toHaveLength(1);
 expect(groups[0].stageLogs.persistence).toHaveLength(1);
 expect(groups[0].recordCount).toBe(1);
 expect(groups[1].hasWarning).toBe(true);
 expect(groups[1].recordCount).toBe(1);
 });
});
