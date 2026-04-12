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

/** HTTP status from API failures (duck-typed so checks work if `instanceof ApiError` fails across bundles). */
export function httpErrorStatus(error: unknown): number | undefined {
  if (error instanceof ApiError) return error.status;
  if (typeof error === "object" && error !== null && "status" in error) {
    const s = (error as { status: unknown }).status;
    return typeof s === "number" && Number.isFinite(s) ? s : undefined;
  }
  return undefined;
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
  // Single origin per process: multi-host fallback retries can hit a different API instance
  // (stale data, wrong cookies). Use the same resolution path as getApiBaseUrl().
  return [getApiBaseUrl()];
}

async function retrySequentially<T>(
  operation: (attempt: number) => Promise<T>,
  {
    maxAttempts,
    backoffMs = 200,
    shouldRetry,
  }: {
    maxAttempts: number;
    backoffMs?: number;
    shouldRetry: (error: unknown) => boolean;
  },
): Promise<T> {
  async function run(attempt: number): Promise<T> {
    try {
      return await operation(attempt);
    } catch (error) {
      if (attempt >= maxAttempts || !shouldRetry(error)) {
        throw error;
      }
      await delay(backoffMs * 2 ** (attempt - 1));
      return run(attempt + 1);
    }
  }

  return run(1);
}

type ResponseParser<T> = (response: Response) => Promise<T>;
type RequestMethod = "POST" | "PUT" | "PATCH" | "DELETE";
type ResponseKind = "json" | "text" | "blob";
type BodyRequestMethod = Exclude<RequestMethod, "DELETE">;

function buildRequestHeaders(init: RequestInit | undefined) {
  const headers = init?.headers;
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return {
    ...(headers ?? {}),
  };
}

async function fetchApiResponse(baseUrl: string, path: string, init?: RequestInit) {
  try {
    return await fetch(`${baseUrl}${path}`, {
      ...init,
      cache: "no-store",
      credentials: "include",
      headers: buildRequestHeaders(init),
    });
  } catch (error) {
    throw error instanceof Error ? error : new Error("Failed to reach API.");
  }
}

async function requestWithParser<T>(
  path: string,
  parser: ResponseParser<T>,
  init?: RequestInit,
): Promise<T> {
  const maxAttempts = 3;
  let lastError: ApiError | null = null;
  let lastFetchError: Error | null = null;
  const candidateBaseUrls = getApiBaseUrlCandidates();
  const hasConfiguredBaseUrl = Boolean(process.env.NEXT_PUBLIC_API_BASE_URL?.trim()) || candidateBaseUrls.length === 1;

  for (const baseUrl of candidateBaseUrls) {
    try {
      return await retrySequentially(
        async () => {
          let response: Response;
          try {
            response = await fetchApiResponse(baseUrl, path, init);
          } catch (error) {
            lastFetchError = error instanceof Error ? error : new Error("Failed to reach API.");
            throw lastFetchError;
          }

          if (response.ok) {
            resolvedBaseUrl = baseUrl;
            return parser(response);
          }

          const body = await readErrorBody(response);
          const message = body || response.statusText || "Request failed";
          const error = new ApiError(message, response.status, body);
          lastError = error;

          if (response.status === 404 && hasConfiguredBaseUrl) {
            throw error;
          }
          if (!error.isRetryable) {
            throw error;
          }
          throw error;
        },
        {
          maxAttempts,
          shouldRetry: (error) =>
            !(error instanceof ApiError) || error.isRetryable,
        },
      );
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status !== 404) {
          throw error;
        }
        lastError = error;
        break;
      }
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

function withJsonHeaders(init?: RequestInit): RequestInit {
  return {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init?.headers
        : {
            "Content-Type": "application/json",
            ...(init?.headers ?? {}),
          },
  };
}

async function parseResponseBody<T>(
  response: Response,
  responseKind: ResponseKind,
): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }

  const contentLength = response.headers.get("content-length");
  if (contentLength === "0") {
    return undefined as T;
  }

  if (responseKind === "text") {
    return response.text() as Promise<T>;
  }
  if (responseKind === "blob") {
    return response.blob() as Promise<T>;
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

function requestWithResponseType<T>(
  path: string,
  responseKind: ResponseKind,
  init?: RequestInit,
): Promise<T> {
  return requestWithParser(
    path,
    (response) => parseResponseBody<T>(response, responseKind),
    responseKind === "json" ? withJsonHeaders(init) : init,
  );
}

function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return requestWithResponseType<T>(path, "json", init);
}

function requestWithBody<T>(
  method: BodyRequestMethod,
  path: string,
  body: unknown,
): Promise<T> {
  return requestJson<T>(path, {
    method,
    body: body instanceof FormData ? body : JSON.stringify(body),
  });
}

export const apiClient = {
  get: <T,>(path: string) => requestWithResponseType<T>(path, "json"),
  getText: (path: string) => requestWithResponseType<string>(path, "text"),
  getBlob: (path: string) => requestWithResponseType<Blob>(path, "blob"),
  post: <T,>(path: string, body: unknown) => requestWithBody<T>("POST", path, body),
  postForm: <T,>(path: string, body: unknown) => requestWithBody<T>("POST", path, body),
  put: <T,>(path: string, body: unknown) => requestWithBody<T>("PUT", path, body),
  patch: <T,>(path: string, body: unknown) => requestWithBody<T>("PATCH", path, body),
  delete: <T,>(path: string) => requestJson<T>(path, { method: "DELETE" }),
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
