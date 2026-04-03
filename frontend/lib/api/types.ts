export type User = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type CrawlRun = {
  id: number;
  user_id: number;
  run_type: string;
  url: string;
  status: string;
  surface: string;
  settings: Record<string, unknown>;
  requested_fields: string[];
  result_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type ReviewSelection = {
  source_field: string;
  output_field: string;
  selected: boolean;
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
  records: CrawlRecord[];
};

export type CrawlCreatePayload = {
  run_type: "crawl" | "batch";
  url?: string;
  urls?: string[];
  surface: string;
  settings?: Record<string, unknown>;
  additional_fields?: string[];
};
