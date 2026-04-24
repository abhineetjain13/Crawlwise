import { cleanup, fireEvent, render, screen, waitFor } from"@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from"vitest";

import { STORAGE_KEYS } from"../../lib/constants/storage-keys";
import { UI_DELAYS } from"../../lib/constants/timing";
import { TopBarProvider } from"../layout/top-bar-context";
import { CrawlConfigScreen } from"./crawl-config-screen";

const {
 replaceMock,
 refreshMock,
 createCsvCrawlMock,
 createCrawlMock,
 getDomainRunProfileMock,
 listSelectorsMock,
} = vi.hoisted(() => ({
 replaceMock: vi.fn(),
 refreshMock: vi.fn(),
 createCsvCrawlMock: vi.fn(),
 createCrawlMock: vi.fn(),
 getDomainRunProfileMock: vi.fn(),
 listSelectorsMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
 useRouter: () => ({
  replace: replaceMock,
  refresh: refreshMock,
 }),
}));

vi.mock("../../lib/api", () => ({
 api: {
 createCsvCrawl: createCsvCrawlMock,
 createCrawl: createCrawlMock,
 getDomainRunProfile: getDomainRunProfileMock,
 listSelectors: listSelectorsMock,
 },
}));

function renderConfigScreen() {
 render(
 <TopBarProvider>
 <CrawlConfigScreen requestedTab={null} requestedCategoryMode={null} requestedPdpMode={null} />
 </TopBarProvider>,
 );
}

describe("CrawlConfigScreen bulk prefill", () => {
 beforeEach(() => {
 vi.clearAllMocks();
 window.sessionStorage.clear();
 getDomainRunProfileMock.mockResolvedValue({
 domain: "example.com",
 surface: "ecommerce_listing",
 saved_run_profile: null,
 });
 listSelectorsMock.mockResolvedValue([]);
 createCrawlMock.mockResolvedValue({ run_id: 321 });
 });

 afterEach(() => {
 cleanup();
 });

 it("restores the jobs domain from batch prefill storage", async () => {
 window.sessionStorage.setItem(
 STORAGE_KEYS.BULK_PREFILL,
 JSON.stringify({
 domain:"jobs",
 urls: ["https://jobs.example.com/posting/1"],
 }),
 );

 renderConfigScreen();

 await waitFor(() => {
 expect(replaceMock).toHaveBeenCalledWith("/crawl?module=pdp&mode=batch");
 });

 await waitFor(() => {
 expect(screen.getByRole("button", { name:"Jobs"})).toHaveAttribute("aria-pressed","true");
 });

 expect(screen.getByLabelText("Bulk URLs input")).toHaveValue("https://jobs.example.com/posting/1");
 });

 it("loads domain memory as soon as the target URL is entered", async () => {
 listSelectorsMock.mockResolvedValue([
 {
 id: 7,
 domain: "example.com",
 surface: "ecommerce_listing",
 field_name: "price",
 css_selector: ".product-price",
 xpath: null,
 regex: null,
 status: "validated",
 source: "domain_memory",
 is_active: true,
 created_at: "2026-04-23T00:00:00Z",
 updated_at: "2026-04-23T00:00:00Z",
 },
 ]);

 renderConfigScreen();

 fireEvent.change(screen.getByLabelText("Target URL input"), {
 target: { value: "https://example.com/collections/chairs" },
 });

 await waitFor(() => {
 expect(getDomainRunProfileMock).toHaveBeenCalledWith({
 url: "https://example.com/collections/chairs",
 surface: "ecommerce_listing",
 });
 expect(listSelectorsMock).toHaveBeenCalledWith({ domain: "example.com" });
 }, { timeout: UI_DELAYS.DEBOUNCE_MS * 6 });

 fireEvent.click(screen.getByRole("button", { name:"Advanced" }));

 expect(await screen.findByDisplayValue("price")).toBeInTheDocument();
 expect(screen.queryByText("Loaded 1 saved selector from domain memory.")).not.toBeInTheDocument();
 });

 it("does not apply proxy defaults from the saved domain run profile", async () => {
 getDomainRunProfileMock.mockResolvedValue({
 domain: "example.com",
 surface: "ecommerce_listing",
 saved_run_profile: {
 version: 1,
 fetch_profile: {
 fetch_mode: "browser_only",
 extraction_source: "raw_html",
 js_mode: "auto",
 include_iframes: false,
 traversal_mode: null,
 request_delay_ms: 500,
 max_pages: 10,
 max_scrolls: 10,
 },
 locality_profile: {
 geo_country: "auto",
 language_hint: null,
 currency_hint: null,
 },
 diagnostics_profile: {
 capture_html: true,
 capture_screenshot: false,
 capture_network: "matched_only",
 capture_response_headers: true,
 capture_browser_diagnostics: true,
 },
 source_run_id: 11,
 saved_at: "2026-04-23T00:00:00Z",
 },
 });

 renderConfigScreen();

 fireEvent.change(screen.getByLabelText("Target URL input"), {
 target: { value: "https://example.com/collections/chairs" },
 });

 await waitFor(() => {
 expect(getDomainRunProfileMock).toHaveBeenCalledWith({
 url: "https://example.com/collections/chairs",
 surface: "ecommerce_listing",
 });
 }, { timeout: UI_DELAYS.DEBOUNCE_MS * 6 });

 fireEvent.click(screen.getByRole("button", { name:"Advanced" }));

 await waitFor(() => {
 expect(screen.queryByLabelText("Proxy pool input")).not.toBeInTheDocument();
 });
 });

 it("refreshes the route after launching a crawl so the new run screen loads immediately", async () => {
 renderConfigScreen();

 fireEvent.change(screen.getByLabelText("Target URL input"), {
 target: { value: "https://example.com/collections/chairs" },
 });

 fireEvent.click(screen.getByRole("button", { name: "Start Crawl" }));

 await waitFor(() => {
 expect(createCrawlMock).toHaveBeenCalled();
 expect(replaceMock).toHaveBeenCalledWith("/crawl?run_id=321");
 expect(refreshMock).toHaveBeenCalledTimes(1);
 });
 });
});
