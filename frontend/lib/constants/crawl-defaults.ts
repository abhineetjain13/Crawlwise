export const CRAWL_DEFAULTS = {
  REQUEST_DELAY_MS: 500,
  MAX_RECORDS: 100,
  MAX_PAGES: 10,
  SCROLL_THRESHOLD_PX: 50,
  TABLE_PAGE_SIZE: 25,
  MAX_LIVE_LOGS: 500,
} as const;

export const CRAWL_LIMITS = {
  MIN_REQUEST_DELAY_MS: 100, // Keep a small floor to avoid rapid-fire requests that trigger rate limits or IP bans.
  MAX_REQUEST_DELAY_MS: 5000,
  MIN_RECORDS: 1,
  MAX_RECORDS: 10000,
  MIN_PAGES: 1,
  MAX_PAGES: 500,
} as const;
