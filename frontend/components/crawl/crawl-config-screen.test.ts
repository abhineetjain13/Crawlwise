import { describe, expect, it } from "vitest";

import { buildDispatch } from "./crawl-config-screen";
import type { FieldRow } from "./shared";
import type { CrawlConfig } from "../../lib/api/types";

function baseConfig(overrides: Partial<CrawlConfig> = {}): CrawlConfig {
 return {
 module:"category",
 domain:"commerce",
 mode:"single",
 target_url:"https://example.com/collections/chairs",
 bulk_urls:"",
 csv_file: null,
 smart_extraction: false,
 advanced_enabled: false,
 advanced_mode:"auto",
 request_delay_ms: 2000,
 max_records: 100,
 max_pages: 5,
 max_scrolls: 10,
 respect_robots_txt: true,
 proxy_enabled: false,
 proxy_lines: [],
 additional_fields: [],
 ...overrides,
 };
}

describe("buildDispatch", () => {
 it("defaults category single runs to ecommerce listing surface", () => {
 const dispatch = buildDispatch(baseConfig());

 expect(dispatch.runType).toBe("crawl");
 expect(dispatch.surface).toBe("ecommerce_listing");
 expect(dispatch.url).toBe("https://example.com/collections/chairs");
 });

 it("keeps commerce listing when the URL is job-like", () => {
 const dispatch = buildDispatch(
 baseConfig({
 target_url:"https://workforcenow.adp.com/careers",
 }),
 );

 expect(dispatch.surface).toBe("ecommerce_listing");
 });

 it("maps jobs category runs to job listing surface", () => {
 const dispatch = buildDispatch(
 baseConfig({
 domain:"jobs",
 target_url:"https://example.com/anything",
 }),
 );

 expect(dispatch.surface).toBe("job_listing");
 });

 it("preserves advanced_mode auto when auto is selected", () => {
 const dispatch = buildDispatch(
 baseConfig({
 advanced_enabled: true,
 advanced_mode:"auto",
 }),
 );

 expect(dispatch.settings.advanced_enabled).toBe(true);
 expect(dispatch.settings.advanced_mode).toBe("auto");
 });

 it("preserves view_all for user-owned settings (backend resolves traversal)", () => {
 const dispatch = buildDispatch(
 baseConfig({
 advanced_enabled: true,
 advanced_mode:"view_all",
 }),
 );

 expect(dispatch.settings.advanced_mode).toBe("view_all");
 });

 it("persists the robots toggle in settings", () => {
 const dispatch = buildDispatch(
 baseConfig({
 respect_robots_txt: false,
 }),
 );

 expect(dispatch.settings.respect_robots_txt).toBe(false);
 });

 it("submits pdp batch as ecommerce detail with URL list", () => {
 const dispatch = buildDispatch(
 baseConfig({
 module:"pdp",
 mode:"batch",
 target_url:"",
 bulk_urls:"https://example.com/p/1\nhttps://example.com/p/2",
 }),
 );

 expect(dispatch.runType).toBe("batch");
 expect(dispatch.surface).toBe("ecommerce_detail");
 expect(dispatch.urls).toEqual(["https://example.com/p/1","https://example.com/p/2"]);
 expect(dispatch.settings.urls).toEqual(["https://example.com/p/1","https://example.com/p/2"]);
 });

 it("maps jobs pdp batch runs to job detail surface", () => {
 const dispatch = buildDispatch(
 baseConfig({
 module:"pdp",
 domain:"jobs",
 mode:"batch",
 target_url:"",
 bulk_urls:"https://recruiting.ultipro.com/org/JobBoard/id/OpportunityDetail?opportunityId=1",
 }),
 );

 expect(dispatch.surface).toBe("job_detail");
 });

 it("throws when batch mode has no URLs", () => {
 expect(() =>
 buildDispatch(
 baseConfig({
 module:"pdp",
 mode:"batch",
 target_url:"",
 bulk_urls:"",
 }),
 ),
 ).toThrow("Batch crawl needs at least one URL.");
 });

 it("includes CSS selectors in the extraction contract", () => {
 const fieldRows: FieldRow[] = [
 {
 id:"field-1",
 fieldName:"price",
 cssSelector:".product-price",
 xpath:"",
 regex:"",
 cssState:"valid",
 xpathState:"idle",
 regexState:"idle",
 },
 ];

 const dispatch = buildDispatch(baseConfig(), fieldRows);

 expect(dispatch.settings.extraction_contract).toEqual([
 {
 field_name:"price",
 css_selector:".product-price",
 xpath: undefined,
 regex: undefined,
 },
 ]);
 });

 it("preserves raw additional field labels in dispatch settings", () => {
 const dispatch = buildDispatch(
 baseConfig({
 module:"pdp",
 mode:"batch",
 target_url:"",
 bulk_urls:"https://example.com/p/1",
 additional_fields: ["Features & Benefits","Product Story"],
 }),
 );

 expect(dispatch.additionalFields).toEqual(["Features & Benefits","Product Story"]);
 expect(dispatch.settings.additional_fields).toEqual(["Features & Benefits","Product Story"]);
 });
});
