type TelemetryPayload = Record<string, unknown>;

const isBrowser = typeof window !== "undefined";
const TELEMETRY_ENDPOINT = "/api/telemetry/events";

function safeString(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  if (value == null) {
    return "";
  }
  return String(value);
}

function normalizeErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return safeString(error) || "Unknown error";
}

export function trackEvent(name: string, payload: TelemetryPayload = {}) {
  if (!isBrowser) {
    return;
  }

  const event = {
    name,
    payload,
    ts: new Date().toISOString(),
    path: window.location.pathname,
  };

  if (process.env.NODE_ENV !== "production") {
    // Keep local and test runs noise-free but observable.
    console.debug("[telemetry:event]", event);
    return;
  }

  try {
    const body = JSON.stringify(event);
    if (typeof navigator !== "undefined" && "sendBeacon" in navigator) {
      const payloadBlob = new Blob([body], { type: "application/json" });
      navigator.sendBeacon(TELEMETRY_ENDPOINT, payloadBlob);
      return;
    }
    void fetch(TELEMETRY_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    });
  } catch {
    // Telemetry must never block user actions.
  }
}

export function telemetryErrorPayload(error: unknown, extra: TelemetryPayload = {}) {
  return {
    ...extra,
    error_message: normalizeErrorMessage(error),
  };
}
