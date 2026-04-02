"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Badge, Card } from "../../components/ui/primitives";
import { EmptyPanel, PageHeader, SectionHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";

export default function RunsPage() {
  const { data } = useQuery({ queryKey: ["runs"], queryFn: api.listCrawls });

  return (
    <div className="space-y-6">
      <PageHeader title="Runs" description="Status, type, and destination." />
      <Card className="space-y-4">
        <SectionHeader title="History" />
        {data?.items?.length ? (
          <div className="grid gap-3">
            {data.items.map((run) => (
              <Link
                key={run.id}
                href={`/runs/${run.id}`}
                className="rounded-2xl border border-border bg-panel-strong/60 p-4 transition hover:-translate-y-0.5 hover:border-brand/40"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 space-y-1">
                    <p className="truncate text-sm font-semibold text-foreground">{run.url || `Run ${run.id}`}</p>
                    <p className="text-xs uppercase tracking-[0.18em] text-muted">
                      {run.run_type} · {run.surface}
                    </p>
                  </div>
                  <Badge tone={run.status === "completed" ? "success" : "warning"}>{run.status}</Badge>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyPanel title="No runs available" description="Submitted crawls will appear here." />
        )}
      </Card>
    </div>
  );
}
