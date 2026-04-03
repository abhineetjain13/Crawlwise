import { apiClient } from "./client";
import type { CrawlCreatePayload, CrawlLog, CrawlRecord, CrawlRun, Dashboard, Paginated, ReviewPayload, ReviewSelection, User } from "./types";

export const api = {
  register: (email: string, password: string) =>
    apiClient.post<User>("/api/auth/register", { email, password }),
  login: (email: string, password: string) =>
    apiClient.post<{ access_token: string; user: User }>("/api/auth/login", { email, password }),
  me: () => apiClient.get<User>("/api/auth/me"),
  dashboard: () => apiClient.get<Dashboard>("/api/dashboard"),
  resetApplicationData: () => apiClient.post<Record<string, number | boolean>>("/api/dashboard/reset-data", {}),
  createCrawl: (payload: CrawlCreatePayload) => apiClient.post<{ run_id: number }>("/api/crawls", payload),
  createCsvCrawl: (payload: {
    file: File;
    surface: string;
    additionalFields: string[];
    settings: Record<string, unknown>;
  }) => {
    const form = new FormData();
    form.append("file", payload.file);
    form.append("surface", payload.surface);
    form.append("additional_fields", payload.additionalFields.join(","));
    form.append("settings_json", JSON.stringify(payload.settings));
    return apiClient.postForm<{ run_id: number; url_count: number }>("/api/crawls/csv", form);
  },
  listCrawls: (params?: { status?: string; run_type?: string; url_search?: string; page?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.run_type) query.set("run_type", params.run_type);
    if (params?.url_search) query.set("url_search", params.url_search);
    if (params?.page !== undefined) query.set("page", String(params.page));
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    return apiClient.get<Paginated<CrawlRun>>(`/api/crawls${query.size ? `?${query.toString()}` : ""}`);
  },
  getCrawl: (runId: number) => apiClient.get<CrawlRun>(`/api/crawls/${runId}`),
  getRecords: (runId: number, params?: { page?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.page !== undefined) query.set("page", String(params.page));
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    return apiClient.get<Paginated<CrawlRecord>>(`/api/crawls/${runId}/records${query.size ? `?${query.toString()}` : ""}`);
  },
  getCrawlLogs: (runId: number) => apiClient.get<CrawlLog[]>(`/api/crawls/${runId}/logs`),
  exportCsv: (runId: number) => `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"}/api/crawls/${runId}/export/csv`,
  exportJson: (runId: number) => `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"}/api/crawls/${runId}/export/json`,
  getReview: (runId: number) => apiClient.get<ReviewPayload>(`/api/review/${runId}`),
  saveReview: (runId: number, payload: { selections: ReviewSelection[]; extra_fields: string[] }) =>
    apiClient.post(`/api/review/${runId}/save`, payload),
  listUsers: () => apiClient.get<Paginated<User>>("/api/users"),
  listSelectors: () => apiClient.get<Array<Record<string, unknown>>>("/api/selectors"),
  listJobs: () => apiClient.get<Array<Record<string, unknown>>>("/api/jobs/active"),
  listLlmConfigs: () => apiClient.get<Array<Record<string, unknown>>>("/api/llm/config"),
};
