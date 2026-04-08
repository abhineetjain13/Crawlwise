import { expect, test } from "@playwright/test";

test("smoke: login to crawl and see exports", async ({ page }) => {
  await page.route("**/api/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user: {
          id: 1,
          email: "qa@example.com",
          role: "admin",
          is_active: true,
          created_at: "2026-04-08T10:00:00Z",
          updated_at: "2026-04-08T10:00:00Z",
        },
      }),
    });
  });

  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        email: "qa@example.com",
        role: "admin",
        is_active: true,
        created_at: "2026-04-08T10:00:00Z",
        updated_at: "2026-04-08T10:00:00Z",
      }),
    });
  });

  await page.route("**/api/dashboard", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_runs: 0,
        active_runs: 0,
        total_records: 0,
        recent_runs: [],
        top_domains: [],
      }),
    });
  });

  await page.route("**/api/crawls", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ run_id: 101 }),
      });
      return;
    }
    await route.fallback();
  });

  await page.route("**/api/crawls/101", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 101,
        user_id: 1,
        run_type: "crawl",
        url: "https://example.com/products/chair",
        status: "completed",
        surface: "ecommerce_detail",
        settings: {},
        requested_fields: [],
        result_summary: { extraction_verdict: "success", record_count: 1 },
        created_at: "2026-04-08T10:00:00Z",
        updated_at: "2026-04-08T10:05:00Z",
        completed_at: "2026-04-08T10:05:00Z",
      }),
    });
  });

  await page.route("**/api/crawls/101/records**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: 1,
            run_id: 101,
            source_url: "https://example.com/products/chair",
            data: { title: "Chair", url: "https://example.com/products/chair" },
            raw_data: {},
            discovered_data: {},
            source_trace: {},
            raw_html_path: null,
            created_at: "2026-04-08T10:00:00Z",
          },
        ],
        meta: { page: 1, limit: 1000, total: 1 },
      }),
    });
  });

  await page.route("**/api/crawls/101/logs**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("qa@example.com");
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/dashboard|crawl/);
  await page.goto("/crawl");
  await page.getByLabel("Target URL input").fill("https://example.com/products/chair");
  await page.getByRole("button", { name: "Start Crawl" }).click();

  await expect(page).toHaveURL(/run_id=101/);
  await expect(page.getByRole("button", { name: "Excel (CSV)" })).toBeVisible();
  await expect(page.getByRole("button", { name: "JSON" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Markdown" }).first()).toBeVisible();
});
