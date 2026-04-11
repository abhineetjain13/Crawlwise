import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const originalApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

describe("apiClient", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  });

  afterEach(() => {
    if (originalApiBaseUrl) {
      process.env.NEXT_PUBLIC_API_BASE_URL = originalApiBaseUrl;
    } else {
      delete process.env.NEXT_PUBLIC_API_BASE_URL;
    }
  });

  it("throws ApiError for successful non-json response with body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>ok</html>", {
          status: 200,
          headers: { "content-type": "text/html" },
        }),
      ),
    );

    const { apiClient } = await import("./client");
    await expect(apiClient.get("/api/example")).rejects.toThrow("Expected JSON response from API.");
  });

  it("validates configured API base URL contract early", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "localhost";
    const { getApiBaseUrl } = await import("./client");

    expect(() => getApiBaseUrl()).toThrow(
      "NEXT_PUBLIC_API_BASE_URL must be a valid absolute URL",
    );
  });

  it("rejects configured API base URL with unsupported protocol", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "ftp://api.example.com";
    const { getApiBaseUrl } = await import("./client");

    expect(() => getApiBaseUrl()).toThrow("NEXT_PUBLIC_API_BASE_URL must use http:// or https://.");
  });

  it("normalizes a valid configured API base URL", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.com/";
    const { getApiBaseUrl } = await import("./client");

    expect(getApiBaseUrl()).toBe("https://api.example.com");
  });

  it("keeps a single-origin policy after 404 responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("Not Found", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const { apiClient } = await import("./client");
    await expect(apiClient.get<{ ok: boolean }>("/api/ping")).rejects.toThrow("Not Found");

    expect(fetchMock).toHaveBeenCalledTimes(1);

    const firstUrl = String(fetchMock.mock.calls[0]?.[0] ?? "");
    expect(firstUrl).not.toEqual("");
  });

  it("httpErrorStatus reads status from ApiError and duck-typed errors", async () => {
    const { ApiError, httpErrorStatus } = await import("./client");
    const apiErr = new ApiError("x", 403, "{}");
    expect(httpErrorStatus(apiErr)).toBe(403);
    expect(httpErrorStatus({ status: 401 })).toBe(401);
    expect(httpErrorStatus(new Error("no"))).toBeUndefined();
  });
});
