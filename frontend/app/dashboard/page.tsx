"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, Button, Card, Metric } from "../../components/ui/primitives";
import { EmptyPanel, JsonPanel, MetricGrid, PageHeader, SectionHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";

export default function DashboardPage() {
  const { data, refetch } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const [isResetting, setIsResetting] = useState(false);
  const [resetError, setResetError] = useState("");

  async function handleResetData() {
    const confirmed = window.confirm(
      "Delete and reset all app data to the starting state? This clears crawl runs, records, logs, artifacts, saved cookies, selectors, and learned domain mappings.",
    );
    if (!confirmed) {
      return;
    }
    setIsResetting(true);
    setResetError("");
    try {
      await api.resetApplicationData();
      await refetch();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to reset application data.";
      setResetError(message);
      window.alert(message);
    } finally {
      setIsResetting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Runs, records, and live activity."
        actions={
          <Button
            type="button"
            onClick={() => void handleResetData()}
            disabled={isResetting}
            variant="danger"
          >
            {isResetting ? "Resetting..." : "Reset Data"}
          </Button>
        }
      />

      <MetricGrid>
        <Metric label="Total Runs" value={data?.total_runs ?? 0} />
        <Metric label="Active Runs" value={data?.active_runs ?? 0} />
        <Metric label="Total Records" value={data?.total_records ?? 0} />
        <Metric label="Success Rate" value={`${data?.success_rate ?? 0}%`} />
      </MetricGrid>

      {resetError ? (
        <Card className="border-danger/20 bg-danger/10 text-sm text-danger">
          {resetError}
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="space-y-4">
          <SectionHeader title="Recent Runs" description="Latest five." />
          {data?.recent_runs?.length ? (
            <div className="grid gap-3">
              {data.recent_runs.map((run) => (
                <div key={run.id} className="rounded-[var(--radius-lg)] border border-border bg-background-elevated p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <p className="truncate text-sm font-semibold text-foreground">{run.url || `Run ${run.id}`}</p>
                      <p className="label-caps">{run.surface}</p>
                    </div>
                    <Badge tone={getStatusTone(run.status)}>{run.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyPanel title="No runs yet" description="Submit a crawl to populate activity." />
          )}
        </Card>
        <JsonPanel title="Domains">
          <div className="rounded-[var(--radius-lg)] border border-border bg-background-elevated p-4">
            {data?.top_domains?.length ? (
              <div className="grid gap-3">
                {data.top_domains.map((item) => (
                  <div key={item.domain} className="grid grid-cols-[1fr_auto] items-center gap-3">
                    <p className="truncate text-sm text-foreground">{item.domain}</p>
                    <span className="text-sm font-semibold text-muted">{item.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">No domain data.</p>
            )}
          </div>
        </JsonPanel>
      </div>
    </div>
  );
}

function getStatusTone(status: string) {
  if (status === "completed") return "success" as const;
  if (status === "running") return "success" as const;
  if (status === "paused") return "warning" as const;
  if (status === "failed" || status === "killed" || status === "proxy_exhausted") return "danger" as const;
  return "neutral" as const;
}
