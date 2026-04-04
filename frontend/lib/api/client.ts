function normalizeBaseUrl(value: string) {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

let resolvedBaseUrl: string | null = null;
const ACCESS_TOKEN_KEY = "crawlerai-access-token";

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
    resolvedBaseUrl = normalizeBaseUrl(configured);
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

function getApiBaseUrlCandidates() {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) {
    return [normalizeBaseUrl(configured)];
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
  const accessToken = readAccessToken();

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
                ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
              }
            : {
              "Content-Type": "application/json",
              ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
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
        return response.json() as Promise<T>;
      }

      const body = await readErrorBody(response);
      const message = body || response.statusText || "Request failed";
      const error = new ApiError(message, response.status, body);
      lastError = error;

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

export function storeAccessToken(token: string | null | undefined) {
  if (typeof window === "undefined") {
    return;
  }
  if (!token) {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

function readAccessToken() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(ACCESS_TOKEN_KEY) ?? "";
}

export const apiClient = {
  get: <T,>(path: string) => request<T>(path),
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
