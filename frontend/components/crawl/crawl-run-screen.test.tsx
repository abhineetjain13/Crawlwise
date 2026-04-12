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
});
