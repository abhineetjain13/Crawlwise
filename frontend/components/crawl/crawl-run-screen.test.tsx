import { QueryClient, QueryClientProvider } from"@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from"@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from"vitest";

import type { CrawlRecord, CrawlRun, DomainRecipe } from"../../lib/api/types";
import { POLLING_INTERVALS } from"../../lib/constants/timing";
import { TopBarProvider } from"../layout/top-bar-context";
import { CrawlRunScreen, storeProductIntelligencePrefill } from"./crawl-run-screen";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
 useRouter: () => ({
 replace: replaceMock,
 }),
}));

const apiMock = vi.hoisted(() => ({
 getCrawl: vi.fn(),
 getRecords: vi.fn(),
 getCrawlLogs: vi.fn(),
 getMarkdown: vi.fn(),
 killCrawl: vi.fn(),
 getDomainRecipe: vi.fn(),
 promoteDomainRecipeSelectors: vi.fn(),
 saveDomainRunProfile: vi.fn(),
 applyDomainRecipeFieldAction: vi.fn(),
 deleteSelector: vi.fn(),
 exportCsv: vi.fn(() =>"/export.csv"),
 exportJson: vi.fn(() =>"/export.json"),
 exportMarkdown: vi.fn(() =>"/export.md"),
}));

vi.mock("../../lib/api", () => ({
 api: apiMock,
}));

function terminalRun(runId: number): CrawlRun {
  return {
 id: runId,
 user_id: 1,
 run_type:"crawl",
 url:"https://example.com/products/chair",
 status:"completed",
 surface:"ecommerce_detail",
 settings: {},
 requested_fields: [],
 result_summary: {
 extraction_verdict:"success",
 record_count: 2,
 },
 created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 updated_at: new Date("2026-04-08T10:05:00Z").toISOString(),
 completed_at: new Date("2026-04-08T10:05:00Z").toISOString(),
  };
}

function runningRun(runId: number): CrawlRun {
  return {
  id: runId,
  user_id: 1,
  run_type:"crawl",
  url:"https://example.com/products/chair",
  status:"running",
  surface:"ecommerce_detail",
  settings: {},
  requested_fields: [],
  result_summary: {
  extraction_verdict:"unknown",
  progress: 0,
  record_count: 0,
  current_url_index: 1,
  total_urls: 5,
  },
  created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
  updated_at: new Date("2026-04-08T10:01:00Z").toISOString(),
  completed_at: null,
  };
}

function makeRecord(id: number): CrawlRecord {
 return {
 id,
 run_id: 101,
 source_url: `https://example.com/p/${id}`,
 data: { title: `Item ${id}`, url: `https://example.com/p/${id}` },
 raw_data: {},
 discovered_data: {},
 source_trace: {},
 raw_html_path: null,
 created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 };
}

function makeDomainRecipe(): DomainRecipe {
 return {
 run_id: 101,
 domain:"example.com",
 surface:"ecommerce_detail",
 requested_field_coverage: {
 requested: ["title","price","brand"],
 found: ["title","price"],
 missing: ["brand"],
 },
 acquisition_evidence: {
 actual_fetch_method:"browser",
 browser_used: true,
 browser_reason:"http-escalation",
 acquisition_summary: {
 browser_used_urls: 1,
 acquisition_ms_total: 4200,
 },
 cookie_memory_available: true,
 },
 field_learning: [
 {
 field_name:"price",
 value:"Rs. 999",
 source_labels: ["dom_selector"],
 selector_kind:"css_selector",
 selector_value:".price",
 source_record_ids: [1],
 feedback: null,
 },
 {
 field_name:"brand",
 value:"Acme",
 source_labels: ["json_ld"],
 selector_kind: null,
 selector_value: null,
 source_record_ids: [1],
 feedback: null,
 },
 ],
 selector_candidates: [
 {
 candidate_key:"price|css_selector|.price",
 field_name:"price",
 selector_kind:"css_selector",
 selector_value:".price",
 selector_source:"domain_memory",
 sample_value:"Rs. 999",
 source_record_ids: [1],
 source_run_id: 101,
 saved_selector_id: null,
 already_saved: false,
 final_field_source:"dom_selector",
 },
 {
 candidate_key:"title|css_selector|.title",
 field_name:"title",
 selector_kind:"css_selector",
 selector_value:".title",
 selector_source:"domain_memory",
 sample_value:"Chair Prime",
 source_record_ids: [1],
 source_run_id: 101,
 saved_selector_id: 22,
 already_saved: true,
 final_field_source:"dom_selector",
 },
 ],
 affordance_candidates: {
 accordions: [".details-accordion"],
 tabs: [],
 carousels: [],
 shadow_hosts: [],
 iframe_promotion: null,
 browser_required: true,
 },
 saved_selectors: [
 {
 id: 22,
 domain:"example.com",
 surface:"ecommerce_detail",
 field_name:"title",
 css_selector:".title",
 xpath: null,
 regex: null,
 status:"validated",
 sample_value:"Chair Prime",
 source:"domain_recipe",
 source_run_id: 88,
 is_active: true,
 created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 updated_at: new Date("2026-04-08T10:00:00Z").toISOString(),
 },
 ],
 saved_run_profile: {
 version: 1,
 fetch_profile: {
 fetch_mode:"http_then_browser",
 extraction_source:"rendered_dom",
 js_mode:"enabled",
 include_iframes: false,
 traversal_mode:"paginate",
 request_delay_ms: 1200,
 max_pages: 8,
 max_scrolls: 12,
 },
 locality_profile: {
 geo_country:"IN",
 language_hint:"en-IN",
 currency_hint:"INR",
 },
 diagnostics_profile: {
 capture_html: true,
 capture_screenshot: false,
 capture_network:"matched_only",
 capture_response_headers: true,
 capture_browser_diagnostics: true,
 },
 source_run_id: 101,
 saved_at:"2026-04-08T10:05:00Z",
 },
 };
}

function renderRunScreen(runId = 101) {
 const queryClient = new QueryClient({
 defaultOptions: {
 queries: {
 retry: false,
 },
 },
 });
 render(
 <QueryClientProvider client={queryClient}>
 <TopBarProvider>
 <CrawlRunScreen runId={runId} />
 </TopBarProvider>
 </QueryClientProvider>,
 );
 return { queryClient };
}

function renderRunScreenWithClient(queryClient: QueryClient, runId = 101) {
 render(
 <QueryClientProvider client={queryClient}>
 <TopBarProvider>
 <CrawlRunScreen runId={runId} />
 </TopBarProvider>
 </QueryClientProvider>,
 );
}

describe("CrawlRunScreen", () => {
 afterEach(() => {
 vi.useRealTimers();
 });

 beforeEach(() => {
 vi.clearAllMocks();
 window.sessionStorage.clear();
 apiMock.getCrawl.mockResolvedValue(terminalRun(101));
 apiMock.getRecords.mockImplementation(async (_runId: number, params?: { page?: number; limit?: number }) => {
 const limit = params?.limit ?? 100;
 const total = 2;
 return {
 items: Array.from({ length: Math.min(limit, total) }, (_, index) => makeRecord(index + 1)),
 meta: { page: 1, limit, total },
 };
 });
 apiMock.getCrawlLogs.mockResolvedValue([]);
 apiMock.getMarkdown.mockResolvedValue("# markdown");
 apiMock.killCrawl.mockResolvedValue({ run_id: 101, status:"killed"});
 apiMock.getDomainRecipe.mockResolvedValue(makeDomainRecipe());
 apiMock.promoteDomainRecipeSelectors.mockResolvedValue([]);
 apiMock.saveDomainRunProfile.mockResolvedValue(makeDomainRecipe().saved_run_profile);
 apiMock.applyDomainRecipeFieldAction.mockResolvedValue({});
 apiMock.deleteSelector.mockResolvedValue(undefined);
 });

 it("prefills Product Intelligence from selected listing records", async () => {
 apiMock.getCrawl.mockResolvedValue({
 ...terminalRun(101),
 surface:"ecommerce_listing",
 url:"https://www.belk.com/category",
 settings: { crawl_module:"category", crawl_mode:"single"},
 });
 apiMock.getRecords.mockResolvedValue({
 items: [
 {
 ...makeRecord(1),
 source_url:"https://www.belk.com/p/1",
 data: { brand:"Levi's", title:"511 Jeans", price:"$59.99", url:"https://www.belk.com/p/1"},
 },
 ],
 meta: { page: 1, limit: 100, total: 1 },
 });

 renderRunScreen();

 const productButton = await screen.findByRole("button", { name:"Product Intelligence (1)"});
 fireEvent.click(productButton);

 expect(replaceMock).toHaveBeenCalledWith("/product-intelligence");
 expect(JSON.parse(window.sessionStorage.getItem("product-intelligence-prefill-v1") || "{}")).toEqual({
 source_run_id: 101,
 source_domain:"https://www.belk.com/category",
 records: [
 {
 id: 1,
 run_id: 101,
 source_url:"https://www.belk.com/p/1",
 data: { brand:"Levi's", title:"511 Jeans", price:"$59.99", url:"https://www.belk.com/p/1"},
 },
 ],
 });
 });

 it("falls back to reduced Product Intelligence prefill when session storage is full", () => {
 const stored = new Map<string, string>();
 const setItemMock = vi.fn((key: string, value: string) => {
 stored.set(key, value);
 });
 const consoleSpy = vi.spyOn(console,"error").mockImplementation(() => {});
 setItemMock.mockImplementationOnce(() => {
 throw new DOMException("Quota exceeded","QuotaExceededError");
 });
 const storage = {
 setItem: setItemMock,
 getItem: (key: string) => stored.get(key) ?? null,
 removeItem: (key: string) => {
 stored.delete(key);
 },
 } as unknown as Storage;
 try {
 storeProductIntelligencePrefill(
 {
 source_run_id: 101,
 source_domain:"https://www.belk.com/category",
 records: [
 {
 id: 1,
 run_id: 101,
 source_url:"https://www.belk.com/p/1",
 data: { brand:"Levi's", title:"511 Jeans", price:"$59.99", url:"https://www.belk.com/p/1"},
 },
 ],
 },
 storage,
 );

 expect(consoleSpy).toHaveBeenCalled();
 expect(JSON.parse(storage.getItem("product-intelligence-prefill-v1") || "{}")).toEqual({
 source_run_id: 101,
 source_domain:"https://www.belk.com/category",
 records: [
 {
 id: 1,
 run_id: 101,
 source_url:"https://www.belk.com/p/1",
 data: {},
 },
 ],
 });
 } finally {
 consoleSpy.mockRestore();
 }
 });

 it("prefetches markdown before the Markdown tab is opened", async () => {
 renderRunScreen();

 const markdownButtons = await screen.findAllByRole("button", { name:"Markdown"});
 const markdownTabButton = markdownButtons.at(-1);
 expect(markdownTabButton).toBeTruthy();
 expect(apiMock.getMarkdown).toHaveBeenCalledTimes(1);

 fireEvent.click(markdownTabButton!);

 await waitFor(() => {
 expect(apiMock.getMarkdown).toHaveBeenCalledTimes(2);
 });
 });

 it("renders markdown from the existing export endpoint in the Markdown tab", async () => {
 apiMock.getMarkdown.mockResolvedValue("# Widget Prime\n\nBuilt for long mileage.");

 renderRunScreen();

 const markdownButtons = await screen.findAllByRole("button", { name:"Markdown"});
 fireEvent.click(markdownButtons.at(-1)!);

 expect(await screen.findByText("Widget Prime")).toBeInTheDocument();
 expect(screen.getByText("Built for long mileage.")).toBeInTheDocument();
 });

 it("reports when no reusable cookie state was observed for a browser run", async () => {
 apiMock.getDomainRecipe.mockResolvedValue({
 ...makeDomainRecipe(),
 acquisition_evidence: {
 ...makeDomainRecipe().acquisition_evidence,
 cookie_memory_available: false,
 },
 });

 renderRunScreen();

 const learningButtons = await screen.findAllByRole("button", { name:"Learning"});
 fireEvent.click(learningButtons.at(-1)!);

 expect(await screen.findByText(/Cookie Memory: No reusable state observed/i)).toBeInTheDocument();
 });

 it("renders completed summary chips from persisted backend values", async () => {
 apiMock.getCrawl.mockResolvedValue({
 ...terminalRun(101),
 result_summary: {
 extraction_verdict:"success",
 record_count: 2,
 duration_ms: 65_000,
 quality_summary: {
 level:"high",
 },
 },
 });
 apiMock.getRecords.mockResolvedValue({
 items: [],
 meta: { page: 1, limit: 100, total: 0 },
 });

 renderRunScreen();

 expect(await screen.findByText("Time:")).toBeInTheDocument();
 expect(screen.getByText("1m 5s")).toBeInTheDocument();
 expect(screen.getByText("Verdict:")).toBeInTheDocument();
 expect(screen.getByText("Success")).toBeInTheDocument();
 expect(screen.getByText("Quality:")).toBeInTheDocument();
 expect(screen.getByText("High")).toBeInTheDocument();
 });

 it("keeps the crawl step marked active after terminal completion", async () => {
 apiMock.getRecords.mockResolvedValue({
 items: [],
 meta: { page: 1, limit: 100, total: 0 },
 });

 renderRunScreen();

 await screen.findByText("completed");
 const crawlStep = screen.getAllByText("Crawl")
 .map((element) => element.closest("span"))
 .find((element) => element?.className.includes("rounded-[var(--radius-md)]"));
 const completeStep = screen.getAllByText("Complete")
 .map((element) => element.closest("span"))
 .find((element) => element?.className.includes("rounded-[var(--radius-md)]"));

 expect(crawlStep).toHaveClass("bg-accent-subtle","text-accent");
 expect(completeStep).toHaveClass("bg-accent-subtle","text-accent");
 });

 it("uses live table totals and current URL index for status-bar records/pages when summary counts are zero", async () => {
 apiMock.getCrawl.mockResolvedValue(runningRun(101));
 apiMock.getRecords.mockResolvedValue({
 items: [makeRecord(1), makeRecord(2)],
 meta: { page: 1, limit: 100, total: 2 },
 });

 renderRunScreen();

 await screen.findByText("Live Log Stream");
 await waitFor(() => {
 const recordsLabel = screen.getByText("Records");
 const pagesLabel = screen.getByText("Pages");
 expect(recordsLabel.previousElementSibling).toHaveTextContent("2");
 expect(pagesLabel.previousElementSibling).toHaveTextContent("1");
 });
 });

 it("supports progressive table loading for large result sets", async () => {
 apiMock.getRecords.mockImplementation(async (_runId: number, params?: { page?: number; limit?: number }) => {
 const page = Math.max(1, params?.page ?? 1);
 const limit = params?.limit ?? 100;
 const total = 150;
 const start = (page - 1) * limit;
 const count = Math.max(0, Math.min(limit, total - start));
 return {
 items: Array.from({ length: count }, (_, index) => makeRecord(start + index + 1)),
 meta: { page, limit, total },
 };
 });

 renderRunScreen();
 await screen.findAllByRole("button", { name:"Markdown"});

 await waitFor(() => {
 expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 1, limit: 100 });
 });

 const loadMoreButton = await screen.findByRole("button", { name:"Load More"});
 fireEvent.click(loadMoreButton);

 await waitFor(() => {
 expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 2, limit: 100 });
 });

 await waitFor(() => {
 expect(screen.queryByRole("button", { name:"Load More"})).not.toBeInTheDocument();
 });
 });

 it("shows recoverable panel refresh errors when records polling fails", async () => {
 apiMock.getRecords.mockRejectedValueOnce(new Error("records fetch failed"));

 renderRunScreen();

 expect(await screen.findByText("Some live panels failed to refresh")).toBeInTheDocument();
 expect(
 await screen.findByText((content) => content.includes("Unable to refresh") && content.includes("records fetch failed")),
 ).toBeInTheDocument();
 expect(screen.getByRole("button", { name:"Retry failed panels"})).toBeInTheDocument();
 });

 it("refetches table records on mount even if the cache contains a fresh empty page", async () => {
 const queryClient = new QueryClient({
 defaultOptions: {
 queries: {
 retry: false,
 staleTime: 60_000,
 },
 },
 });

 queryClient.setQueryData(["crawl-run", 101], terminalRun(101));
 queryClient.setQueryData(["crawl-records-table", 101, 1], {
 items: [],
 meta: { page: 1, limit: 100, total: 0 },
 });

 apiMock.getRecords.mockResolvedValue({
 items: [makeRecord(1), makeRecord(2)],
 meta: { page: 1, limit: 100, total: 2 },
 });

 renderRunScreenWithClient(queryClient);

 await waitFor(() => {
 expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 1, limit: 100 });
 });

 await waitFor(() => {
 expect(screen.getByText("Item 1")).toBeInTheDocument();
 });
 });

 it("keeps cached latest-run table rows visible when reopening from history", async () => {
 const queryClient = new QueryClient({
 defaultOptions: {
 queries: {
 retry: false,
 staleTime: 60_000,
 },
 },
 });

 const cachedRows = {
 items: [makeRecord(1), makeRecord(2)],
 meta: { page: 1, limit: 100, total: 2 },
 };

 queryClient.setQueryData(["crawl-run", 101], terminalRun(101));
 queryClient.setQueryData(["crawl-records-table", 101, 1], cachedRows);

 apiMock.getRecords.mockResolvedValue(cachedRows);

 renderRunScreenWithClient(queryClient);

 expect(await screen.findByText("Item 1")).toBeInTheDocument();

 await waitFor(() => {
 expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 1, limit: 100 });
 });
 });

 it("refetches recent completed runs when summary records are present but the first table fetch is empty", async () => {
 const completedAt = new Date().toISOString();
 apiMock.getCrawl.mockResolvedValue({
 ...terminalRun(101),
 updated_at: completedAt,
 completed_at: completedAt,
 result_summary: {
 extraction_verdict:"success",
 record_count: 2,
 },
 });

 let callCount = 0;
 apiMock.getRecords.mockImplementation(async (_runId: number, params?: { page?: number; limit?: number }) => {
 callCount += 1;
 const limit = params?.limit ?? 100;
 if (callCount === 1) {
 return {
 items: [],
 meta: { page: 1, limit, total: 0 },
 };
 }
 return {
 items: [makeRecord(1), makeRecord(2)],
 meta: { page: 1, limit, total: 2 },
 };
 });

 renderRunScreen();

 await waitFor(() => {
 expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 1, limit: 100 });
 });

 await new Promise((resolve) => window.setTimeout(resolve, POLLING_INTERVALS.RECORDS_MS + 100));

 await waitFor(() => {
 expect(apiMock.getRecords.mock.calls.length).toBeGreaterThanOrEqual(2);
 });

 await waitFor(() => {
 expect(screen.getByText("Item 1")).toBeInTheDocument();
 });
 });

 it("retries both table and JSON record queries during terminal reconciliation", async () => {
  apiMock.getCrawl.mockResolvedValue({
  ...terminalRun(101),
  updated_at:"2026-04-08T10:05:00Z",
  completed_at:"2026-04-08T10:05:00Z",
  result_summary: {
  extraction_verdict:"success",
  record_count: 2,
  },
  });

  let tableCalls = 0;
  let jsonCalls = 0;
  apiMock.getRecords.mockImplementation(async (_runId: number, params?: { page?: number; limit?: number }) => {
  const limit = params?.limit ?? 100;
  if (params?.page === 1) {
  tableCalls += 1;
  return tableCalls === 1
  ? { items: [], meta: { page: 1, limit, total: 0 } }
  : { items: [makeRecord(1), makeRecord(2)], meta: { page: 1, limit, total: 2 } };
  }
  jsonCalls += 1;
  return jsonCalls === 1
  ? { items: [], meta: { page: 1, limit, total: 0 } }
  : { items: [makeRecord(1), makeRecord(2)], meta: { page: 1, limit, total: 2 } };
  });

  renderRunScreen();

  await waitFor(() => {
  expect(apiMock.getRecords.mock.calls).toEqual(
  expect.arrayContaining([
  [101, { page: 1, limit: 100 }],
  [101, { limit: 100 }],
  ]),
  );
  });

  await new Promise((resolve) => window.setTimeout(resolve, POLLING_INTERVALS.RECORDS_MS + 100));

  await waitFor(() => {
  expect(tableCalls).toBeGreaterThanOrEqual(2);
  expect(jsonCalls).toBeGreaterThanOrEqual(2);
  });
 });

 it("reconciles older completed runs when the first table fetch is empty but records are expected", async () => {
 apiMock.getCrawl.mockResolvedValue({
 ...terminalRun(101),
 updated_at:"2026-04-08T10:05:00Z",
 completed_at:"2026-04-08T10:05:00Z",
 result_summary: {
 extraction_verdict:"success",
 record_count: 2,
 },
 });

 let callCount = 0;
 apiMock.getRecords.mockImplementation(async (_runId: number, params?: { page?: number; limit?: number }) => {
 callCount += 1;
 const limit = params?.limit ?? 100;
 if (callCount === 1) {
 return {
 items: [],
 meta: { page: 1, limit, total: 0 },
 };
 }
 return {
 items: [makeRecord(1), makeRecord(2)],
 meta: { page: 1, limit, total: 2 },
 };
 });

 renderRunScreen();

 await waitFor(() => {
 expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 1, limit: 100 });
 });

 await new Promise((resolve) => window.setTimeout(resolve, POLLING_INTERVALS.RECORDS_MS + 100));

 await waitFor(() => {
 expect(apiMock.getRecords.mock.calls.length).toBeGreaterThanOrEqual(2);
 });

 await waitFor(() => {
 expect(screen.getByText("Item 1")).toBeInTheDocument();
 });
 });

 it("renders decoded Thai URLs in the JSON preview without changing the underlying records payload", async () => {
 apiMock.getRecords.mockResolvedValue({
 items: [
 {
 ...makeRecord(1),
 data: {
 title:"Item 1",
 url:"https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3",
 },
 },
 ],
 meta: { page: 1, limit: 400, total: 1 },
 });

 renderRunScreen();

 const jsonButtons = await screen.findAllByRole("button", { name:"JSON"});
 fireEvent.click(jsonButtons.at(-1)!);

 await waitFor(() => {
 expect(screen.getByText(/https:\/\/www\.shop\.ving\.run\/product\/สีดำ/)).toBeInTheDocument();
 });

 expect(screen.queryByText(/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3/)).not.toBeInTheDocument();
 });

 it("prefills batch crawl with the originating jobs domain from listing runs", async () => {
 apiMock.getCrawl.mockResolvedValue({
 ...terminalRun(101),
 surface:"job_listing",
 url:"https://example.com/careers",
 settings: { crawl_module:"category", crawl_mode:"single"},
 });
 apiMock.getRecords.mockResolvedValue({
 items: [
 {
 ...makeRecord(1),
 source_url:"https://jobs.example.com/posting/1",
 data: { title:"Role 1", url:"https://jobs.example.com/posting/1"},
 },
 ],
 meta: { page: 1, limit: 100, total: 1 },
 });

 renderRunScreen();

 const batchButton = await screen.findByRole("button", { name:"Batch Crawl (1)"});
 fireEvent.click(batchButton);

 expect(replaceMock).toHaveBeenCalledWith("/crawl?module=pdp&mode=batch");
 expect(window.sessionStorage.getItem("bulk-crawl-prefill-v1")).toBe(
 JSON.stringify({
 domain:"jobs",
 urls: ["https://jobs.example.com/posting/1"],
 }),
 );
 });

 it("keeps batch crawl result URLs available after switching from table to logs", async () => {
 apiMock.getCrawl.mockResolvedValue({
 ...terminalRun(101),
 surface:"ecommerce_listing",
 url:"https://www.karenmillen.com/categories/womens-dresses",
 settings: { crawl_module:"category", crawl_mode:"single"},
 result_summary: {
 extraction_verdict:"partial",
 record_count: 2,
 },
 });
 apiMock.getRecords.mockImplementation(async (_runId: number, params?: { page?: number; limit?: number }) => {
 const limit = params?.limit ?? 100;
 return {
 items: [
 {
 ...makeRecord(1),
 source_url:"https://www.karenmillen.com/p/1",
 data: { title:"Dress 1", url:"https://www.karenmillen.com/p/1"},
 },
 {
 ...makeRecord(2),
 source_url:"https://www.karenmillen.com/p/2",
 data: { title:"Dress 2", url:"https://www.karenmillen.com/p/2"},
 },
 ],
 meta: { page: 1, limit, total: 2 },
 };
 });

 renderRunScreen();

 const logsTab = await screen.findByRole("button", { name:"Logs"});
 fireEvent.click(logsTab);

 const batchButton = await screen.findByRole("button", { name:"Batch Crawl (2)"});
 fireEvent.click(batchButton);

 expect(replaceMock).toHaveBeenCalledWith("/crawl?module=pdp&mode=batch");
 expect(window.sessionStorage.getItem("bulk-crawl-prefill-v1")).toBe(
 JSON.stringify({
 domain:"commerce",
 urls: [
"https://www.karenmillen.com/p/1",
"https://www.karenmillen.com/p/2",
 ],
 }),
 );
 });

 it("triggers direct CSV export downloads from the terminal workspace", async () => {
 const clickSpy = vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(() => {});
 try {
 renderRunScreen();

 const button = await screen.findByRole("button", { name:"Excel (CSV)"});
 fireEvent.click(button);

 expect(apiMock.exportCsv).toHaveBeenCalledWith(101);
 expect(clickSpy).toHaveBeenCalledTimes(1);
 } finally {
 clickSpy.mockRestore();
 }
 });

 it("renders completed-run learning and run-config tabs", async () => {
 renderRunScreen();

 expect(await screen.findByRole("button", { name:"Learning"})).toBeInTheDocument();
 expect(screen.getByRole("button", { name:"Run Config"})).toBeInTheDocument();

 fireEvent.click(screen.getByRole("button", { name:"Learning"}));
 expect(await screen.findByRole("heading", { name:"Run Learning" })).toBeInTheDocument();
 expect(screen.getAllByRole("button", { name:"Keep" }).length).toBeGreaterThan(0);

 fireEvent.click(screen.getByRole("button", { name:"Run Config"}));
 expect(await screen.findByRole("heading", { name:"Run Config" })).toBeInTheDocument();
 expect(screen.getByRole("button", { name:"Save Run Profile"})).toBeInTheDocument();
 });

 it("renders structured learning values with JSON serialization", async () => {
 apiMock.getDomainRecipe.mockResolvedValue({
 ...makeDomainRecipe(),
 field_learning: [
 {
 field_name:"variant_axes",
 value: { Size: ["S","M"] },
 source_labels: ["dom_selector"],
 selector_kind:"css_selector",
 selector_value:".sizes",
 source_record_ids: [1],
 feedback: null,
 },
 ],
 });

 renderRunScreen();

 fireEvent.click(await screen.findByRole("button", { name:"Learning"}));
 expect(await screen.findByText(/Value: \{"Size":\["S","M"\]\}/)).toBeInTheDocument();
 });

 it("applies keep and reject field learning actions from the completed-run panel", async () => {
 renderRunScreen();

 fireEvent.click(await screen.findByRole("button", { name:"Learning"}));
 expect(await screen.findByRole("heading", { name:"Run Learning" })).toBeInTheDocument();
 const keepButtons = screen.getAllByRole("button", { name:"Keep" });
 const rejectButtons = screen.getAllByRole("button", { name:"Reject" });

 fireEvent.click(keepButtons[0]);
 await waitFor(() => {
 expect(apiMock.applyDomainRecipeFieldAction).toHaveBeenCalledWith(101, {
 field_name:"price",
 action:"keep",
 selector_kind:"css_selector",
 selector_value:".price",
 source_record_ids: [1],
 });
 });

 fireEvent.click(rejectButtons[1]);
 await waitFor(() => {
 expect(apiMock.applyDomainRecipeFieldAction).toHaveBeenCalledWith(101, {
 field_name:"brand",
 action:"reject",
 selector_kind: null,
 selector_value: null,
 source_record_ids: [1],
 });
 });
 });

 it("saves the edited domain run profile from the completed-run panel", async () => {
 renderRunScreen();

 fireEvent.click(await screen.findByRole("button", { name:"Run Config"}));
 expect(await screen.findByRole("heading", { name:"Run Config" })).toBeInTheDocument();
 fireEvent.click(screen.getByRole("combobox", { name:"Fetch Mode" }));
 fireEvent.click(await screen.findByRole("option", { name:"Browser Only" }));
 fireEvent.change(screen.getByRole("textbox", { name:"Geo Country" }), { target: { value:"US" } });
 fireEvent.click(screen.getByRole("button", { name:"Save Run Profile"}));

 await waitFor(() => {
 expect(apiMock.saveDomainRunProfile).toHaveBeenCalledWith(101, {
 profile: expect.objectContaining({
 fetch_profile: expect.objectContaining({
 fetch_mode:"browser_only",
 }),
 locality_profile: expect.objectContaining({
 geo_country:"US",
 }),
 }),
 });
 });
 });
});
