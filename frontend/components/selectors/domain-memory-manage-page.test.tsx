import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TopBarProvider } from "../layout/top-bar-context";
import DomainMemoryManagePage from "../../app/selectors/manage/page";

const apiMock = vi.hoisted(() => ({
 listSelectors: vi.fn(),
 listDomainRunProfiles: vi.fn(),
 listDomainCookieMemory: vi.fn(),
 listDomainFieldFeedback: vi.fn(),
 listCrawls: vi.fn(),
 updateSelector: vi.fn(),
 deleteSelector: vi.fn(),
 deleteSelectorsByDomain: vi.fn(),
}));

vi.mock("../../lib/api", () => ({
 api: apiMock,
}));

describe("DomainMemoryManagePage", () => {
 beforeEach(() => {
 vi.clearAllMocks();
 apiMock.listSelectors.mockResolvedValue([
 {
 id: 11,
 domain: "example.com",
 surface: "ecommerce_detail",
 field_name: "price",
 css_selector: ".price",
 xpath: null,
 regex: null,
 status: "validated",
 sample_value: "$19.99",
 source: "domain_recipe",
 source_run_id: 101,
 is_active: true,
 created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 updated_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 },
 ]);
 apiMock.listDomainRunProfiles.mockResolvedValue([
 {
 id: 7,
 domain: "example.com",
 surface: "ecommerce_detail",
 profile: {
 version: 1,
 fetch_profile: {
 fetch_mode: "http_then_browser",
 extraction_source: "rendered_dom",
 js_mode: "enabled",
 include_iframes: false,
 traversal_mode: "paginate",
 request_delay_ms: 1200,
 max_pages: 8,
 max_scrolls: 12,
 },
 locality_profile: {
 geo_country: "IN",
 language_hint: "en-IN",
 currency_hint: "INR",
 },
 diagnostics_profile: {
 capture_html: true,
 capture_screenshot: false,
 capture_network: "matched_only",
 capture_response_headers: true,
 capture_browser_diagnostics: true,
 },
 source_run_id: 101,
 saved_at: new Date("2026-04-08T10:05:00Z").toISOString(),
 },
 created_at: new Date("2026-04-08T10:05:00Z").toISOString(),
 updated_at: new Date("2026-04-08T10:05:00Z").toISOString(),
 },
 ]);
 apiMock.listDomainCookieMemory.mockResolvedValue([
 {
 id: 4,
 domain: "example.com",
 cookie_count: 3,
 origin_count: 1,
 updated_at: new Date("2026-04-08T10:05:00Z").toISOString(),
 },
 {
 id: 5,
 domain: "owned-session-test.example.com",
 cookie_count: 1,
 origin_count: 0,
 updated_at: new Date("2026-04-08T10:05:00Z").toISOString(),
 },
 ]);
 apiMock.listDomainFieldFeedback.mockResolvedValue([
 {
 id: 5,
 domain: "example.com",
 surface: "ecommerce_detail",
 field_name: "price",
 action: "keep",
 source_kind: "selector",
 source_value: ".price",
 source_run_id: 101,
 selector_kind: "css_selector",
 selector_value: ".price",
 source_record_ids: [1],
 created_at: new Date("2026-04-08T10:06:00Z").toISOString(),
 },
 ]);
 apiMock.listCrawls.mockResolvedValue({
 items: [
 {
 id: 101,
 user_id: 1,
 run_type: "crawl",
 url: "https://example.com/products/widget",
 status: "completed",
 surface: "ecommerce_detail",
 settings: {},
 requested_fields: [],
 result_summary: { domain: "example.com" },
 created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 updated_at: new Date("2026-04-08T10:10:00Z").toISOString(),
 completed_at: new Date("2026-04-08T10:10:00Z").toISOString(),
 },
 ],
 meta: { page: 1, limit: 200, total: 1 },
 });
 apiMock.updateSelector.mockImplementation(async (_id: number, payload: Record<string, unknown>) => ({
 id: 11,
 domain: "example.com",
 surface: "ecommerce_detail",
 field_name: String(payload.field_name ?? "price"),
 css_selector: payload.css_selector ?? ".price",
 xpath: payload.xpath ?? null,
 regex: payload.regex ?? null,
 status: "validated",
 sample_value: "$19.99",
 source: String(payload.source ?? "domain_recipe"),
 source_run_id: 101,
 is_active: Boolean(payload.is_active ?? true),
 created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 updated_at: new Date("2026-04-08T10:10:00Z").toISOString(),
 }));
 apiMock.deleteSelector.mockResolvedValue(undefined);
 apiMock.deleteSelectorsByDomain.mockResolvedValue({ deleted: 1 });
 });

 it("renders the selected domain memory workspace and recent learning", async () => {
 render(
 <TopBarProvider>
 <DomainMemoryManagePage />
 </TopBarProvider>,
 );

 expect(await screen.findByText("Selector Memory")).toBeInTheDocument();
 expect(screen.getAllByText("example.com").length).toBeGreaterThan(0);
 expect(screen.getAllByText("price").length).toBeGreaterThan(0);

 expect(screen.getByRole("button", { name: "Selectors (1)" })).toBeInTheDocument();
 expect(screen.getByRole("button", { name: "Profiles (1)" })).toBeInTheDocument();
 expect(screen.getByRole("button", { name: "Cookies (3)" })).toBeInTheDocument();
 expect(screen.getByRole("button", { name: "Learning (1)" })).toBeInTheDocument();

 fireEvent.click(screen.getByRole("button", { name: "Profiles (1)" }));
 expect(screen.getByText("Run Profile Defaults")).toBeInTheDocument();

 fireEvent.click(screen.getByRole("button", { name: "Cookies (3)" }));
 expect(screen.getByText("Saved Domain Cookies")).toBeInTheDocument();

 fireEvent.click(screen.getByRole("button", { name: "Learning (1)" }));
 expect(screen.getByText("Recent Learning")).toBeInTheDocument();

 expect(screen.queryByText("owned-session-test.example.com")).not.toBeInTheDocument();
 });

 it("edits a saved selector from the domain memory workspace", async () => {
 render(
 <TopBarProvider>
 <DomainMemoryManagePage />
 </TopBarProvider>,
 );

 const editButton = await screen.findByRole("button", { name: "Edit selector" });
 fireEvent.click(editButton);
 fireEvent.change(screen.getByDisplayValue(".price"), { target: { value: ".sale-price" } });
 fireEvent.click(screen.getByRole("button", { name: "Save" }));

 await waitFor(() => {
 expect(apiMock.updateSelector).toHaveBeenCalledWith(11, expect.objectContaining({
 css_selector: ".sale-price",
 }));
 });
 });
});
