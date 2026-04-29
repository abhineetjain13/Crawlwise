import { apiClient, getApiBaseUrl } from "./client";
import type {
 ActiveJob,
 CrawlCreatePayload,
 CrawlLog,
 CrawlRecord,
 CrawlRecordProvenance,
 CrawlRun,
 CrawlSurface,
 Dashboard,
 DomainRecipe,
 DomainCookieMemoryRecord,
 DomainFieldFeedbackRecord,
 DomainRunProfileLookup,
 DomainRunProfileRecord,
 DomainRunProfile,
 FieldCommitPayload,
 FieldCommitResponse,
 LlmConfigCreatePayload,
 LoginResponse,
 Paginated,
 ProductIntelligenceJob,
 ProductIntelligenceDiscoveryPayload,
 ProductIntelligenceDiscoveryResponse,
 ProductIntelligenceJobCreatePayload,
 ProductIntelligenceJobDetail,
 ReviewPayload,
 ReviewSelection,
 SelectorCreatePayload,
 SelectorDomainSummary,
 SelectorRecord,
 SelectorSuggestResponse,
 SelectorTestResponse,
 SelectorUpdatePayload,
 User,
 LlmConfigRecord,
 LlmConfigUpdatePayload,
 LlmProviderCatalogItem,
 LlmConnectionTestResponse,
 LlmCostLogRecord,
} from "./types";

function withQuery(path: string, query: URLSearchParams) {
 const queryString = query.toString();
 return queryString ? `${path}?${queryString}` : path;
}

export const api = {
 register: (email: string, password: string) =>
 apiClient.post<User>("/api/auth/register", { email, password }),
 login: async (email: string, password: string) => {
 const response = await apiClient.post<LoginResponse>("/api/auth/login", { email, password });
 return response;
 },
 me: () => apiClient.get<User>("/api/auth/me"),
 dashboard: () => apiClient.get<Dashboard>("/api/dashboard"),
 resetApplicationData: () => apiClient.post<Record<string, number | boolean>>("/api/dashboard/reset-data", {}),
 createCrawl: (payload: CrawlCreatePayload) => apiClient.post<{ run_id: number }>("/api/crawls", payload),
 createCsvCrawl: (payload: {
 file: File;
 surface: CrawlSurface;
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
 ) => apiClient.post<FieldCommitResponse>(`/api/crawls/${runId}/commit-fields`, { items }),
 getRecords: (runId: number, params?: { page?: number; limit?: number }) => {
 const query = new URLSearchParams();
 if (params?.page !== undefined) query.set("page", String(params.page));
 if (params?.limit !== undefined) query.set("limit", String(params.limit));
 return apiClient.get<Paginated<CrawlRecord>>(withQuery(`/api/crawls/${runId}/records`, query));
 },
 getRecordProvenance: (recordId: number) => apiClient.get<CrawlRecordProvenance>(`/api/records/${recordId}/provenance`),
 getCrawlLogs: (runId: number, params?: { afterId?: number; limit?: number }) => {
 const query = new URLSearchParams();
 if (params?.afterId !== undefined) query.set("after_id", String(params.afterId));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  return apiClient.get<CrawlLog[]>(withQuery(`/api/crawls/${runId}/logs`, query));
 },
 discoverProductIntelligence: (payload: ProductIntelligenceDiscoveryPayload) =>
 apiClient.post<ProductIntelligenceDiscoveryResponse>("/api/product-intelligence/discover", payload),
 createProductIntelligenceJob: (payload: ProductIntelligenceJobCreatePayload) =>
 apiClient.post<ProductIntelligenceJob>("/api/product-intelligence/jobs", payload),
 listProductIntelligenceJobs: (params?: { limit?: number }) => {
 const query = new URLSearchParams();
 if (params?.limit !== undefined) query.set("limit", String(params.limit));
 return apiClient.get<ProductIntelligenceJob[]>(withQuery("/api/product-intelligence/jobs", query));
 },
 getProductIntelligenceJob: (jobId: number) =>
 apiClient.get<ProductIntelligenceJobDetail>(`/api/product-intelligence/jobs/${jobId}`),
 reviewProductIntelligenceMatch: (
 jobId: number,
 matchId: number,
 payload: { action: "pending"|"accepted"|"rejected" },
 ) => apiClient.post<{ match_id: number; review_status: string }>(`/api/product-intelligence/jobs/${jobId}/matches/${matchId}/review`, payload),
 getMarkdown: (runId: number) => apiClient.getText(`/api/crawls/${runId}/export/markdown`),
 downloadCsv: (runId: number) => apiClient.getBlob(`/api/crawls/${runId}/export/csv`),
 downloadJson: (runId: number) => apiClient.getBlob(`/api/crawls/${runId}/export/json`),
 downloadMarkdown: (runId: number) => apiClient.getBlob(`/api/crawls/${runId}/export/markdown`),
 exportCsv: (runId: number) => `${getApiBaseUrl()}/api/crawls/${runId}/export/csv`,
 exportJson: (runId: number) => `${getApiBaseUrl()}/api/crawls/${runId}/export/json`,
 exportMarkdown: (runId: number) => `${getApiBaseUrl()}/api/crawls/${runId}/export/markdown`,
 getReview: (runId: number) => apiClient.get<ReviewPayload>(`/api/review/${runId}`),
 reviewHtml: (runId: number) => `${getApiBaseUrl()}/api/review/${runId}/artifact-html`,
 saveReview: (runId: number, payload: { selections: ReviewSelection[]; extra_fields: string[] }) =>
 apiClient.post(`/api/review/${runId}/save`, payload),
 getDomainRunProfile: (params: { url: string; surface: CrawlSurface }) => {
 const query = new URLSearchParams();
 query.set("url", params.url);
 query.set("surface", params.surface);
 return apiClient.get<DomainRunProfileLookup>(withQuery("/api/crawls/domain-run-profile", query));
 },
 listDomainRunProfiles: (params?: { domain?: string; surface?: string }) => {
 const query = new URLSearchParams();
 if (params?.domain) query.set("domain", params.domain);
 if (params?.surface) query.set("surface", params.surface);
 return apiClient.get<DomainRunProfileRecord[]>(withQuery("/api/crawls/domain-memory/run-profiles", query));
 },
 listDomainCookieMemory: (params?: { domain?: string }) => {
 const query = new URLSearchParams();
 if (params?.domain) query.set("domain", params.domain);
 return apiClient.get<DomainCookieMemoryRecord[]>(withQuery("/api/crawls/domain-memory/cookies", query));
 },
 listDomainFieldFeedback: (params?: { domain?: string; surface?: string; limit?: number }) => {
 const query = new URLSearchParams();
 if (params?.domain) query.set("domain", params.domain);
 if (params?.surface) query.set("surface", params.surface);
 if (params?.limit !== undefined) query.set("limit", String(params.limit));
 return apiClient.get<DomainFieldFeedbackRecord[]>(withQuery("/api/crawls/domain-memory/field-feedback", query));
 },
 getDomainRecipe: (runId: number) => apiClient.get<DomainRecipe>(`/api/crawls/${runId}/domain-recipe`),
 promoteDomainRecipeSelectors: (
 runId: number,
 payload: {
 selectors: Array<{
 candidate_key: string;
 field_name: string;
 selector_kind: string;
 selector_value: string;
 sample_value?: string | null;
 }>;
 },
 ) => apiClient.post<SelectorRecord[]>(`/api/crawls/${runId}/domain-recipe/promote-selectors`, payload),
 saveDomainRunProfile: (
 runId: number,
 payload: { profile: DomainRunProfile },
 ) => apiClient.post<DomainRunProfile>(`/api/crawls/${runId}/domain-recipe/save-run-profile`, payload),
 applyDomainRecipeFieldAction: (
 runId: number,
 payload: {
 field_name: string;
 action: "keep"|"reject";
 selector_kind?: string | null;
 selector_value?: string | null;
 source_record_ids?: number[];
 },
 ) => apiClient.post<Record<string, unknown>>(`/api/crawls/${runId}/domain-recipe/field-action`, payload),
 listUsers: (params?: { search?: string; is_active?: boolean }) => {
 const query = new URLSearchParams();
 if (params?.search) query.set("search", params.search);
 if (params?.is_active !== undefined) query.set("is_active", String(params.is_active));
 return apiClient.get<Paginated<User>>(withQuery("/api/users", query));
 },
 updateUser: (userId: number, payload: Partial<Pick<User,"role"|"is_active">>) =>
 apiClient.patch<User>(`/api/users/${userId}`, payload),
 listSelectors: (params?: { domain?: string; surface?: string }) => {
 const query = new URLSearchParams();
 if (params?.domain) query.set("domain", params.domain);
 if (params?.surface) query.set("surface", params.surface);
 return apiClient.get<SelectorRecord[]>(withQuery("/api/selectors", query));
 },
 listSelectorSummaries: () => apiClient.get<SelectorDomainSummary[]>("/api/selectors/summary"),
 suggestSelectors: (payload: { url: string; expected_columns: string[]; surface?: string }) =>
 apiClient.post<SelectorSuggestResponse>("/api/selectors/suggest", payload),
 createSelector: (payload: SelectorCreatePayload) => apiClient.post<SelectorRecord>("/api/selectors", payload),
 updateSelector: (selectorId: number, payload: SelectorUpdatePayload) =>
 apiClient.put<SelectorRecord>(`/api/selectors/${selectorId}`, payload),
 deleteSelector: (selectorId: number) => apiClient.delete<void>(`/api/selectors/${selectorId}`),
 deleteSelectorsByDomain: (domain: string) =>
 apiClient.delete<{ deleted: number }>(`/api/selectors/domain/${encodeURIComponent(domain)}`),
 testSelector: (payload: { url: string; css_selector?: string | null; xpath?: string | null; regex?: string | null }) =>
 apiClient.post<SelectorTestResponse>("/api/selectors/test", payload),
 selectorPreviewHtml: (url: string) => `${getApiBaseUrl()}/api/selectors/preview-html?url=${encodeURIComponent(url)}`,
 listLlmProviders: () => apiClient.get<LlmProviderCatalogItem[]>("/api/llm/providers"),
 listLlmConfigs: () => apiClient.get<LlmConfigRecord[]>("/api/llm/configs"),
 createLlmConfig: (payload: LlmConfigCreatePayload) => apiClient.post<LlmConfigRecord>("/api/llm/configs", payload),
 updateLlmConfig: (configId: number, payload: LlmConfigUpdatePayload) =>
 apiClient.put<LlmConfigRecord>(`/api/llm/configs/${configId}`, payload),
 deleteLlmConfig: (configId: number) => apiClient.delete<void>(`/api/llm/configs/${configId}`),
 testLlmConnection: (payload: { provider: string; model: string; api_key?: string | null }) =>
 apiClient.post<LlmConnectionTestResponse>("/api/llm/test-connection", payload),
 listLlmCostLog: () => apiClient.get<LlmCostLogRecord[]>("/api/llm/cost-log"),
 listJobs: () => apiClient.get<ActiveJob[]>("/api/jobs/active"),
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
