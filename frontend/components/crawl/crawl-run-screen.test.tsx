import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CrawlRecord, CrawlRun } from "../../lib/api/types";
import { POLLING_INTERVALS } from "../../lib/constants/timing";
import { TopBarProvider } from "../layout/top-bar-context";
import { CrawlRunScreen } from "./crawl-run-screen";

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
  exportCsv: vi.fn(() => "/export.csv"),
  exportJson: vi.fn(() => "/export.json"),
  exportMarkdown: vi.fn(() => "/export.md"),
}));

vi.mock("../../lib/api", () => ({
  api: apiMock,
}));

function terminalRun(runId: number): CrawlRun {
  return {
    id: runId,
    user_id: 1,
    run_type: "crawl",
    url: "https://example.com/products/chair",
    status: "completed",
    surface: "ecommerce_detail",
    settings: {},
    requested_fields: [],
    result_summary: {
      extraction_verdict: "success",
      record_count: 2,
    },
    created_at: new Date("2026-04-08T10:00:00Z").toISOString(),
    updated_at: new Date("2026-04-08T10:05:00Z").toISOString(),
    completed_at: new Date("2026-04-08T10:05:00Z").toISOString(),
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
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
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
    apiMock.killCrawl.mockResolvedValue({ run_id: 101, status: "killed" });
  });

  it("prefetches markdown before the Markdown tab is opened", async () => {
    renderRunScreen();

    const markdownButtons = await screen.findAllByRole("button", { name: "Markdown" });
    const markdownTabButton = markdownButtons.at(-1);
    expect(markdownTabButton).toBeTruthy();
    expect(apiMock.getMarkdown).toHaveBeenCalledTimes(1);

    fireEvent.click(markdownTabButton!);

    await waitFor(() => {
      expect(apiMock.getMarkdown).toHaveBeenCalledTimes(2);
    });
  });

  it("renders completed summary chips from persisted backend values", async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      result_summary: {
        extraction_verdict: "success",
        record_count: 2,
        duration_ms: 65_000,
        quality_summary: {
          level: "high",
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
    await screen.findAllByRole("button", { name: "Markdown" });

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 1, limit: 100 });
    });

    const loadMoreButton = await screen.findByRole("button", { name: "Load More" });
    fireEvent.click(loadMoreButton);

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(101, { page: 2, limit: 100 });
    });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Load More" })).not.toBeInTheDocument();
    });
  });

  it("shows recoverable panel refresh errors when records polling fails", async () => {
    apiMock.getRecords.mockRejectedValueOnce(new Error("records fetch failed"));

    renderRunScreen();

    expect(await screen.findByText("Some live panels failed to refresh")).toBeInTheDocument();
    expect(await screen.findByText(/Unable to refresh records: records fetch failed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry failed panels" })).toBeInTheDocument();
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

  it("refetches recent completed runs when summary records are present but the first table fetch is empty", async () => {
    const completedAt = new Date().toISOString();
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      updated_at: completedAt,
      completed_at: completedAt,
      result_summary: {
        extraction_verdict: "success",
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
            title: "Item 1",
            url: "https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3",
          },
        },
      ],
      meta: { page: 1, limit: 400, total: 1 },
    });

    renderRunScreen();

    const jsonButtons = await screen.findAllByRole("button", { name: "JSON" });
    fireEvent.click(jsonButtons.at(-1)!);

    await waitFor(() => {
      expect(screen.getByText(/https:\/\/www\.shop\.ving\.run\/product\/สีดำ/)).toBeInTheDocument();
    });

    expect(screen.queryByText(/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3/)).not.toBeInTheDocument();
  });

  it("prefills batch crawl with the originating jobs domain from listing runs", async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      surface: "job_listing",
      url: "https://example.com/careers",
      settings: { crawl_module: "category", crawl_mode: "single" },
    });
    apiMock.getRecords.mockResolvedValue({
      items: [
        {
          ...makeRecord(1),
          source_url: "https://jobs.example.com/posting/1",
          data: { title: "Role 1", url: "https://jobs.example.com/posting/1" },
        },
      ],
      meta: { page: 1, limit: 100, total: 1 },
    });

    renderRunScreen();

    const batchButton = await screen.findByRole("button", { name: "Batch Crawl Results (1)" });
    fireEvent.click(batchButton);

    expect(replaceMock).toHaveBeenCalledWith("/crawl?module=pdp&mode=batch");
    expect(window.sessionStorage.getItem("bulk-crawl-prefill-v1")).toBe(
      JSON.stringify({
        domain: "jobs",
        urls: ["https://jobs.example.com/posting/1"],
      }),
    );
  });

  it("keeps batch crawl result URLs available after switching from table to logs", async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      surface: "ecommerce_listing",
      url: "https://www.karenmillen.com/categories/womens-dresses",
      settings: { crawl_module: "category", crawl_mode: "single" },
      result_summary: {
        extraction_verdict: "partial",
        record_count: 2,
      },
    });
    apiMock.getRecords.mockImplementation(async (_runId: number, params?: { page?: number; limit?: number }) => {
      const limit = params?.limit ?? 100;
      return {
        items: [
          {
            ...makeRecord(1),
            source_url: "https://www.karenmillen.com/p/1",
            data: { title: "Dress 1", url: "https://www.karenmillen.com/p/1" },
          },
          {
            ...makeRecord(2),
            source_url: "https://www.karenmillen.com/p/2",
            data: { title: "Dress 2", url: "https://www.karenmillen.com/p/2" },
          },
        ],
        meta: { page: 1, limit, total: 2 },
      };
    });

    renderRunScreen();

    const logsTab = await screen.findByRole("button", { name: "Logs" });
    fireEvent.click(logsTab);

    const batchButton = await screen.findByRole("button", { name: "Batch Crawl Results (2)" });
    fireEvent.click(batchButton);

    expect(replaceMock).toHaveBeenCalledWith("/crawl?module=pdp&mode=batch");
    expect(window.sessionStorage.getItem("bulk-crawl-prefill-v1")).toBe(
      JSON.stringify({
        domain: "commerce",
        urls: [
          "https://www.karenmillen.com/p/1",
          "https://www.karenmillen.com/p/2",
        ],
      }),
    );
  });

  it("triggers direct CSV export downloads from the terminal workspace", async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderRunScreen();

    const button = await screen.findByRole("button", { name: "Excel (CSV)" });
    fireEvent.click(button);

    expect(apiMock.exportCsv).toHaveBeenCalledWith(101);
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });
});
