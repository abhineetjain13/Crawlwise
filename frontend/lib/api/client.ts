function normalizeBaseUrl(value: string) {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function parseConfiguredApiBaseUrl(configured: string) {
  let parsed: URL;
  try {
    parsed = new URL(configured);
  } catch {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL must be a valid absolute URL (for example, http://127.0.0.1:8000).",
    );
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL must use http:// or https://.",
    );
  }
  return normalizeBaseUrl(parsed.toString());
}

let resolvedBaseUrl: string | null = null;

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(message: string, status: number, body: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  get isUnauthorized() {
    return this.status === 401;
  }

  get isRetryable() {
    return this.status >= 500 && this.status < 600;
  }
}

export function getApiBaseUrl() {
  if (resolvedBaseUrl) {
    return resolvedBaseUrl;
  }
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) {
    resolvedBaseUrl = parseConfiguredApiBaseUrl(configured);
    return resolvedBaseUrl;
  }
  if (typeof window !== "undefined") {
    if (process.env.NODE_ENV === "production") {
      throw new Error("NEXT_PUBLIC_API_BASE_URL must be set in production.");
    }
    const { protocol, hostname } = window.location;
    resolvedBaseUrl = `${protocol}//${hostname}:8000`;
    return resolvedBaseUrl;
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be set in production.");
  }
  resolvedBaseUrl = "http://127.0.0.1:8000";
  return resolvedBaseUrl;
}

export function getApiWebSocketBaseUrl() {
  const httpBase = getApiBaseUrl();
  if (httpBase.startsWith("https://")) {
    return `wss://${httpBase.slice("https://".length)}`;
  }
  if (httpBase.startsWith("http://")) {
    return `ws://${httpBase.slice("http://".length)}`;
  }
  return httpBase;
}

function getApiBaseUrlCandidates() {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) {
    return [parseConfiguredApiBaseUrl(configured)];
  }
  if (typeof window === "undefined") {
    return ["http://127.0.0.1:8000", "http://localhost:8000"];
  }
  const { protocol, hostname } = window.location;
  const candidates = [
    `${protocol}//${hostname}:8000`,
    `${protocol}//127.0.0.1:8000`,
    `${protocol}//localhost:8000`,
  ];
  return Array.from(new Set(candidates.map(normalizeBaseUrl)));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const maxAttempts = 3;
  let lastError: ApiError | null = null;
  let lastFetchError: Error | null = null;
  const candidateBaseUrls = getApiBaseUrlCandidates();
  const hasConfiguredBaseUrl = Boolean(process.env.NEXT_PUBLIC_API_BASE_URL?.trim()) || candidateBaseUrls.length === 1;

  for (const baseUrl of candidateBaseUrls) {
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      let response: Response;
      try {
        response = await fetch(`${baseUrl}${path}`, {
          ...init,
          cache: "no-store",
          credentials: "include",
          headers: isFormData
            ? {
                ...(init?.headers ?? {}),
              }
            : {
                "Content-Type": "application/json",
                ...(init?.headers ?? {}),
              },
        });
      } catch (error) {
        lastFetchError = error instanceof Error ? error : new Error("Failed to reach API.");
        if (attempt === maxAttempts) {
          break;
        }
        await delay(200 * 2 ** (attempt - 1));
        continue;
      }

      if (response.ok) {
        resolvedBaseUrl = baseUrl;
        if (response.status === 204) {
          return undefined as T;
        }
        const contentLength = response.headers.get("content-length");
        if (contentLength === "0") {
          return undefined as T;
        }
        const contentType = response.headers.get("content-type") ?? "";
        if (!contentType.includes("application/json")) {
          const text = await response.text();
          if (!text.trim()) {
            return undefined as T;
          }
          throw new ApiError("Expected JSON response from API.", response.status, text);
        }
        return response.json() as Promise<T>;
      }

      const body = await readErrorBody(response);
      const message = body || response.statusText || "Request failed";
      const error = new ApiError(message, response.status, body);
      lastError = error;

      if (response.status === 404 && hasConfiguredBaseUrl) {
        throw error;
      }
      if (!error.isRetryable || attempt === maxAttempts) {
        if (response.status !== 404) {
          throw error;
        }
        break;
      }

      await delay(200 * 2 ** (attempt - 1));
    }
  }

  if (lastError) {
    throw lastError;
  }
  if (lastFetchError) {
    throw new Error(`Failed to reach backend API. Tried: ${candidateBaseUrls.join(", ")}`);
  }
  throw lastError ?? new ApiError("Request failed", 500, "");
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const isFormData = init?.body instanceof FormData;
  const maxAttempts = 3;
  const candidateBaseUrls = getApiBaseUrlCandidates();
  const hasConfiguredBaseUrl = Boolean(process.env.NEXT_PUBLIC_API_BASE_URL?.trim()) || candidateBaseUrls.length === 1;
  let lastError: ApiError | null = null;
  let lastFetchError: Error | null = null;

  for (const baseUrl of candidateBaseUrls) {
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      let response: Response;
      try {
        response = await fetch(`${baseUrl}${path}`, {
          ...init,
          cache: "no-store",
          credentials: "include",
          headers: isFormData
            ? {
                ...(init?.headers ?? {}),
              }
            : {
                ...(init?.headers ?? {}),
              },
        });
      } catch (error) {
        lastFetchError = error instanceof Error ? error : new Error("Failed to reach API.");
        if (attempt === maxAttempts) {
          break;
        }
        await delay(200 * 2 ** (attempt - 1));
        continue;
      }

      if (response.ok) {
        resolvedBaseUrl = baseUrl;
        return await response.text();
      }

      const body = await readErrorBody(response);
      const error = new ApiError(body || response.statusText || "Request failed", response.status, body);
      lastError = error;
      if (response.status === 404 && hasConfiguredBaseUrl) {
        throw error;
      }
      if (!error.isRetryable || attempt === maxAttempts) {
        if (response.status !== 404) {
          throw error;
        }
        break;
      }

      await delay(200 * 2 ** (attempt - 1));
    }
  }

  if (lastError) {
    throw lastError;
  }
  if (lastFetchError) {
    throw new Error(`Failed to reach backend API. Tried: ${candidateBaseUrls.join(", ")}`);
  }
  throw new ApiError("Request failed", 500, "");
}

export const apiClient = {
  get: <T,>(path: string) => request<T>(path),
  getText: (path: string) => requestText(path),
  post: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  postForm: <T,>(path: string, body: FormData) =>
    request<T>(path, { method: "POST", body }),
  put: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};

async function readErrorBody(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      const payload = await response.json();
      if (payload && typeof payload === "object") {
        const detail = (payload as Record<string, unknown>).detail;
        if (typeof detail === "string") {
          return detail;
        }
      }
      return JSON.stringify(payload);
    } catch {
      return response.statusText;
    }
  }

  try {
    return (await response.text()).trim();
  } catch {
    return response.statusText;
  }
}

function delay(ms: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
