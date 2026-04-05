import { apiClient, getApiBaseUrl, storeAccessToken } from "./client";
import type {
  ActiveJob,
  CrawlCreatePayload,
  CrawlLog,
  CrawlRecord,
  CrawlRecordProvenance,
  CrawlRun,
  Dashboard,
  FieldCommitPayload,
  FieldCommitResponse,
  LlmConfigRecord,
  LlmConnectionTestResponse,
  LlmCostLogRecord,
  LlmProviderCatalogItem,
  Paginated,
  ReviewPayload,
  ReviewSelectorPreview,
  ReviewSelection,
  SelectorCreatePayload,
  SelectorRecord,
  SelectorSuggestResponse,
  SelectorTestResponse,
  SelectorUpdatePayload,
  User,
} from "./types";

function withQuery(path: string, query: URLSearchParams) {
  const queryString = query.toString();
  return queryString ? `${path}?${queryString}` : path;
}

export const api = {
  register: (email: string, password: string) =>
    apiClient.post<User>("/api/auth/register", { email, password }),
  login: async (email: string, password: string) => {
    const response = await apiClient.post<{ access_token: string; user: User }>("/api/auth/login", { email, password });
    storeAccessToken(response.access_token);
    return response;
  },
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
    return apiClient.get<Paginated<CrawlRun>>(withQuery("/api/crawls", query));
  },
  getCrawl: (runId: number) => apiClient.get<CrawlRun>(`/api/crawls/${runId}`),
  deleteCrawl: (runId: number) => apiClient.delete<void>(`/api/crawls/${runId}`),
  pauseCrawl: (runId: number) => apiClient.post<{ run_id: number; status: CrawlRun["status"] }>(`/api/crawls/${runId}/pause`, {}),
  resumeCrawl: (runId: number) => apiClient.post<{ run_id: number; status: CrawlRun["status"] }>(`/api/crawls/${runId}/resume`, {}),
  killCrawl: (runId: number) => apiClient.post<{ run_id: number; status: CrawlRun["status"] }>(`/api/crawls/${runId}/kill`, {}),
  commitSelectedFields: async (
    runId: number,
    items: FieldCommitPayload[],
  ) => {
    try {
      return await apiClient.post<FieldCommitResponse>(`/api/crawls/${runId}/commit-fields`, { items });
    } catch (error) {
      const status = error instanceof Error && "status" in error ? Number((error as { status?: unknown }).status) : undefined;
      if (status !== 404) {
        throw error;
      }
      return await apiClient.post<FieldCommitResponse>(`/api/crawls/${runId}/llm-commit`, { items });
    }
  },
  commitLlmSuggestions: (
    runId: number,
    items: Array<{ record_id: number; field_name: string; value: unknown }>,
  ) => apiClient.post<{ run_id: number; updated_records: number; updated_fields: number }>(`/api/crawls/${runId}/llm-commit`, { items }),
  getRecords: (runId: number, params?: { page?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.page !== undefined) query.set("page", String(params.page));
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    return apiClient.get<Paginated<CrawlRecord>>(withQuery(`/api/crawls/${runId}/records`, query));
  },
  getRecordProvenance: (recordId: number) => apiClient.get<CrawlRecordProvenance>(`/api/records/${recordId}/provenance`),
  getCrawlLogs: (runId: number) => apiClient.get<CrawlLog[]>(`/api/crawls/${runId}/logs`),
  exportCsv: (runId: number) => `${getApiBaseUrl()}/api/crawls/${runId}/export/csv`,
  exportJson: (runId: number) => `${getApiBaseUrl()}/api/crawls/${runId}/export/json`,
  getReview: (runId: number) => apiClient.get<ReviewPayload>(`/api/review/${runId}`),
  reviewHtml: (runId: number) => `${getApiBaseUrl()}/api/review/${runId}/artifact-html`,
  saveReview: (runId: number, payload: { selections: ReviewSelection[]; extra_fields: string[] }) =>
    apiClient.post(`/api/review/${runId}/save`, payload),
  previewSelectors: (runId: number, payload: { selectors: SelectorCreatePayload[] }) =>
    apiClient.post<ReviewSelectorPreview>(`/api/review/${runId}/selector-preview`, payload),
  listUsers: (params?: { search?: string; is_active?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.search) query.set("search", params.search);
    if (params?.is_active !== undefined) query.set("is_active", String(params.is_active));
    return apiClient.get<Paginated<User>>(withQuery("/api/users", query));
  },
  updateUser: (userId: number, payload: Partial<Pick<User, "role" | "is_active">>) =>
    apiClient.patch<User>(`/api/users/${userId}`, payload),
  listSelectors: (params?: { domain?: string }) => {
    const query = new URLSearchParams();
    if (params?.domain) query.set("domain", params.domain);
    return apiClient.get<SelectorRecord[]>(withQuery("/api/selectors", query));
  },
  suggestSelectors: (payload: { url: string; expected_columns: string[] }) =>
    apiClient.post<SelectorSuggestResponse>("/api/selectors/suggest", payload),
  createSelector: (payload: SelectorCreatePayload) => apiClient.post<SelectorRecord>("/api/selectors", payload),
  updateSelector: (selectorId: number, payload: SelectorUpdatePayload) =>
    apiClient.put<SelectorRecord>(`/api/selectors/${selectorId}`, payload),
  deleteSelector: (selectorId: number) => apiClient.delete<void>(`/api/selectors/${selectorId}`),
  deleteSelectorsByDomain: (domain: string) =>
    apiClient.delete<{ deleted: number }>(`/api/selectors/domain/${encodeURIComponent(domain)}`),
  clearAllSiteMemory: () => apiClient.delete<{ deleted: number }>("/api/selectors/clear-all"),
  testSelector: (payload: { url: string; css_selector?: string | null; xpath?: string | null; regex?: string | null }) =>
    apiClient.post<SelectorTestResponse>("/api/selectors/test", payload),
  listJobs: () => apiClient.get<ActiveJob[]>("/api/jobs/active"),
  listLlmCatalog: () => apiClient.get<LlmProviderCatalogItem[]>("/api/llm/catalog"),
  listLlmConfigs: () => apiClient.get<LlmConfigRecord[]>("/api/llm/config"),
  createLlmConfig: (payload: {
    provider: string;
    model: string;
    api_key?: string;
    task_type: string;
    per_domain_daily_budget_usd: number;
    global_session_budget_usd: number;
  }) => apiClient.post<LlmConfigRecord>("/api/llm/config", payload),
  updateLlmConfig: (
    configId: number,
    payload: Partial<{
      provider: string;
      model: string;
      api_key: string;
      task_type: string;
      per_domain_daily_budget_usd: number;
      global_session_budget_usd: number;
      is_active: boolean;
    }>,
  ) => apiClient.put<LlmConfigRecord>(`/api/llm/config/${configId}`, payload),
  testLlmConnection: (payload: { provider: string; model: string; api_key?: string }) =>
    apiClient.post<LlmConnectionTestResponse>("/api/llm/test", payload),
  listLlmCostLog: (params?: { page?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.page !== undefined) query.set("page", String(params.page));
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    return apiClient.get<Paginated<LlmCostLogRecord>>(withQuery("/api/llm/cost-log", query));
  },
};

// Named exports for easier consumption in components
export const fetchCrawlRun = api.getCrawl;
export const fetchCrawlRecords = (runId: number) => api.getRecords(runId).then(res => res.items);
export const fetchCrawlRecordMetadata = (runId: number) => api.getRecords(runId, { limit: 1 }).then(res => res.items[0]);
export const fetchCrawlLogs = api.getCrawlLogs;
export const createCrawl = api.createCrawl;
export const pauseCrawlRun = api.pauseCrawl;
export const resumeCrawlRun = api.resumeCrawl;
export const killCrawlRun = api.killCrawl;
export const commitFieldSuggestion = (runId: number, item: { record_id: number; field_name: string; value: unknown }) => 
  api.commitSelectedFields(runId, [item]);
