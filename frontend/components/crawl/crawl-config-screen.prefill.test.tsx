import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { TopBarProvider } from "../layout/top-bar-context";
import { CrawlConfigScreen } from "./crawl-config-screen";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: replaceMock,
  }),
}));

vi.mock("../../lib/api", () => ({
  api: {
    createCsvCrawl: vi.fn(),
    createCrawl: vi.fn(),
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
  });

  afterEach(() => {
    cleanup();
  });

  it("restores the jobs domain from batch prefill storage", async () => {
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        domain: "jobs",
        urls: ["https://jobs.example.com/posting/1"],
      }),
    );

    renderConfigScreen();

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/crawl?module=pdp&mode=batch");
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Jobs" })).toHaveAttribute("aria-pressed", "true");
    });

    expect(screen.getByLabelText("Bulk URLs input")).toHaveValue("https://jobs.example.com/posting/1");
  });
});
