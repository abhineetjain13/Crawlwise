import type { RunStatus } from"../api/types";

export const TERMINAL_STATUSES = new Set<RunStatus>(["completed","killed","failed","proxy_exhausted"]);
export const ACTIVE_STATUSES = new Set<RunStatus>(["pending","running","paused"]);
