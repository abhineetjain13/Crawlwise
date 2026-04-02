"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge, Card, Metric } from "../../components/ui/primitives";
import { EmptyPanel, JsonPanel, MetricGrid, PageHeader, SectionHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";

export default function DashboardPage() {
  const { data } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" description="Runs, records, and live activity." />

      <MetricGrid>
        <Metric label="Total Runs" value={data?.total_runs ?? 0} />
        <Metric label="Active Runs" value={data?.active_runs ?? 0} />
        <Metric label="Total Records" value={data?.total_records ?? 0} />
        <Metric label="Success Rate" value={`${data?.success_rate ?? 0}%`} />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="space-y-4">
          <SectionHeader title="Recent Runs" description="Latest five." />
          {data?.recent_runs?.length ? (
            <div className="grid gap-3">
              {data.recent_runs.map((run) => (
                <div key={run.id} className="rounded-2xl border border-border bg-panel-strong/60 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <p className="truncate text-sm font-semibold text-foreground">{run.url || `Run ${run.id}`}</p>
                      <p className="text-xs uppercase tracking-[0.18em] text-muted">{run.surface}</p>
                    </div>
                    <Badge tone={run.status === "completed" ? "success" : "warning"}>{run.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyPanel title="No runs yet" description="Submit a crawl to populate activity." />
          )}
        </Card>
        <JsonPanel title="Domains">
          <div className="rounded-2xl border border-border bg-panel-strong/60 p-4">
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
