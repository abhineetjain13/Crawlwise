function normalizeBaseUrl(value: string) {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

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
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) {
    return normalizeBaseUrl(configured);
  }
  if (typeof window !== "undefined") {
    if (process.env.NODE_ENV === "production") {
      throw new Error("NEXT_PUBLIC_API_BASE_URL must be set in production.");
    }
    const { protocol, hostname } = window.location;
    return `${protocol}//${hostname}:8000`;
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be set in production.");
  }
  return "http://127.0.0.1:8000";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const maxAttempts = 3;
  let lastError: ApiError | null = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(`${getApiBaseUrl()}${path}`, {
        ...init,
        cache: "no-store",
        credentials: "include",
        headers: isFormData
          ? init?.headers
          : {
              "Content-Type": "application/json",
              ...(init?.headers ?? {}),
            },
      });
    } catch (error) {
      if (attempt === maxAttempts) {
        throw error;
      }
      await delay(200 * 2 ** (attempt - 1));
      continue;
    }

    if (response.ok) {
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
      throw error;
    }

    await delay(200 * 2 ** (attempt - 1));
  }

  throw lastError ?? new ApiError("Request failed", 500, "");
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
