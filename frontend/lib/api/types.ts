export type User = {
  id: number;
  email: string;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type RunStatus =
  | "pending"
  | "running"
  | "paused"
  | "completed"
  | "killed"
  | "failed"
  | "proxy_exhausted";

export type CrawlPhase = "config" | "running" | "complete";

export type CrawlModule = "category" | "pdp";

export type CrawlMode = "single" | "sitemap" | "bulk" | "batch" | "csv";

export type ResultSummary = {
  extraction_verdict?: string;
  record_count?: number;
  domain?: string;
  error?: string;
  current_stage?: string;
  current_url?: string;
  current_url_index?: number;
  total_urls?: number;
  [key: string]: unknown;
};

export type CrawlRun = {
  id: number;
  user_id: number;
  run_type: string;
  url: string;
  status: RunStatus;
  surface: string;
  settings: Record<string, unknown>;
  requested_fields: string[];
  result_summary: ResultSummary;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type ActiveJob = {
  run_id: number;
  status: RunStatus;
  progress: number;
  started_at: string;
  url: string;
  type: string;
  user_id?: number;
  elapsed_seconds?: number;
  records_collected?: number;
  max_records?: number;
};

export type ReviewSelection = {
  source_field: string;
  output_field: string;
  selected: boolean;
};

export type SelectorRuleInput = {
  id?: number | null;
  field_name: string;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  status?: string | null;
  confidence?: number | null;
  sample_value?: string | null;
  source?: string | null;
  is_active?: boolean;
};

export type CrawlRecord = {
  id: number;
  run_id: number;
  source_url: string;
  data: Record<string, unknown>;
  raw_data: Record<string, unknown>;
  discovered_data: Record<string, unknown>;
  source_trace: Record<string, unknown>;
  raw_html_path: string | null;
  created_at: string;
};

export type CrawlLog = {
  id: number;
  level: string;
  message: string;
  created_at: string;
};

export type Paginated<T> = {
  items: T[];
  meta: { page: number; limit: number; total: number };
};

export type Dashboard = {
  total_runs: number;
  active_runs: number;
  total_records: number;
  recent_runs: CrawlRun[];
  top_domains: { domain: string; count: number }[];
  success_rate: number;
};

export type ReviewPayload = {
  run: CrawlRun;
  normalized_fields: string[];
  discovered_fields: string[];
  canonical_fields: string[];
  domain_mapping: Record<string, string>;
  suggested_mapping: Record<string, string>;
  selector_memory: Array<Record<string, unknown>>;
  selector_suggestions: Record<string, Array<Record<string, unknown>>>;
  records: CrawlRecord[];
};

export type SelectorRecord = {
  id: number;
  domain: string;
  field_name: string;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  status: string;
  confidence?: number | null;
  sample_value?: string | null;
  source: string;
  source_run_id?: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ReviewSelectorPreview = {
  records: CrawlRecord[];
};

export type SelectorCreatePayload = {
  domain: string;
  field_name: string;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  status?: string | null;
  confidence?: number | null;
  sample_value?: string | null;
  source?: string | null;
  source_run_id?: number | null;
  is_active?: boolean;
};

export type SelectorUpdatePayload = Partial<SelectorCreatePayload>;

export type SelectorTestResponse = {
  matched_value: string | null;
  count: number;
  selector_used?: string | null;
};

export type SelectorSuggestion = {
  field_name?: string | null;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  sample_value?: string | null;
  source?: string | null;
};

export type SelectorSuggestResponse = {
  suggestions: Record<string, SelectorSuggestion[]>;
};

export type LlmConfigRecord = {
  id: number;
  provider: string;
  model: string;
  api_key_masked: string;
  api_key_set: boolean;
  task_type: string;
  per_domain_daily_budget_usd: string;
  global_session_budget_usd: string;
  is_active: boolean;
  created_at: string;
};

export type LlmProviderCatalogItem = {
  provider: string;
  label: string;
  api_key_set: boolean;
  recommended_models: string[];
};

export type LlmConnectionTestResponse = {
  ok: boolean;
  message: string;
};

export type LlmCostLogRecord = {
  id: number;
  run_id: number | null;
  provider: string;
  model: string;
  task_type: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  domain: string;
  created_at: string;
};

export type CrawlCreatePayload = {
  run_type: "crawl" | "batch" | "csv";
  url?: string;
  urls?: string[];
  surface: string;
  settings?: Record<string, unknown>;
  additional_fields?: string[];
};

export type CrawlConfig = {
  module: CrawlModule;
  mode: CrawlMode;
  target_url: string;
  bulk_urls: string;
  csv_file: File | null;
  smart_extraction: boolean;
  advanced_enabled: boolean;
  request_delay_ms: number;
  max_records: number;
  max_pages: number;
  proxy_enabled: boolean;
  proxy_lines: string[];
  additional_fields: string[];
};
