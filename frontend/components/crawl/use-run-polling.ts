"use client";

import { useEffect, useRef } from "react";

import type { CrawlRun } from "../../lib/api/types";
import { ACTIVE_STATUSES, TERMINAL_STATUSES } from "../../lib/constants/crawl-statuses";

type RefetchableQuery = {
  refetch: () => Promise<unknown>;
};

export function useRunStatusFlags(run: CrawlRun | undefined) {
  const live = Boolean(run && ACTIVE_STATUSES.has(run.status));
  const terminal = Boolean(run && TERMINAL_STATUSES.has(run.status));
  return { live, terminal };
}

export function useTerminalSync(
  run: CrawlRun | undefined,
  terminal: boolean,
  queries: ReadonlyArray<RefetchableQuery>,
) {
  const terminalSyncRef = useRef<string | null>(null);

  useEffect(() => {
    if (!run || !terminal) {
      terminalSyncRef.current = null;
      return;
    }

    const syncKey = `${run.id}:${run.status}:${run.completed_at ?? ""}:${run.updated_at}`;
    if (terminalSyncRef.current === syncKey) {
      return;
    }
    terminalSyncRef.current = syncKey;

    void Promise.allSettled(queries.map((query) => query.refetch()));
  }, [queries, run, terminal]);
}
