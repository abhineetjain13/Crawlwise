import { apiClient } from "./client";
import type { CrawlCreatePayload, CrawlRecord, CrawlRun, Dashboard, Paginated, ReviewPayload, User } from "./types";

export const api = {
  register: (email: string, password: string) =>
    apiClient.post<User>("/api/auth/register", { email, password }),
  login: (email: string, password: string) =>
    apiClient.post<{ access_token: string; user: User }>("/api/auth/login", { email, password }),
  me: () => apiClient.get<User>("/api/auth/me"),
  dashboard: () => apiClient.get<Dashboard>("/api/dashboard"),
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
  listCrawls: () => apiClient.get<Paginated<CrawlRun>>("/api/crawls"),
  getCrawl: (runId: number) => apiClient.get<CrawlRun>(`/api/crawls/${runId}`),
  getRecords: (runId: number) => apiClient.get<Paginated<CrawlRecord>>(`/api/crawls/${runId}/records`),
  getReview: (runId: number) => apiClient.get<ReviewPayload>(`/api/review/${runId}`),
  saveReview: (runId: number, selections: Array<{ source_field: string; output_field: string }>) =>
    apiClient.post(`/api/review/${runId}/save`, { selections }),
  listUsers: () => apiClient.get<Paginated<User>>("/api/users"),
  listSelectors: () => apiClient.get<Array<Record<string, unknown>>>("/api/selectors"),
  listJobs: () => apiClient.get<Array<Record<string, unknown>>>("/api/jobs/active"),
  listLlmConfigs: () => apiClient.get<Array<Record<string, unknown>>>("/api/llm/config"),
};
