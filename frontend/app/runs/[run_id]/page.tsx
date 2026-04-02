"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Button, Card, CodeBlock, Field, Input, Metric } from "../../../components/ui/primitives";
import { JsonPanel, MetricGrid, PageHeader, SectionHeader } from "../../../components/ui/patterns";
import { api } from "../../../lib/api";

export default function RunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const runId = Number(params.run_id);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getCrawl(runId),
    refetchInterval: 3000,
  });
  const recordsQuery = useQuery({ queryKey: ["run-records", runId], queryFn: () => api.getRecords(runId) });
  const reviewQuery = useQuery({ queryKey: ["review", runId], queryFn: () => api.getReview(runId) });

  const discoveredFields = useMemo(() => reviewQuery.data?.discovered_fields ?? [], [reviewQuery.data]);

  async function savePromotion() {
    await api.saveReview(
      runId,
      discoveredFields.map((field) => ({ source_field: field, output_field: mapping[field] || field })),
    );
    await reviewQuery.refetch();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Run #${runId}`}
        description="Normalized output, raw evidence, and promotion mapping."
        actions={
          <Button variant="secondary" onClick={() => runQuery.refetch()}>
            Refresh
          </Button>
        }
      />

      <MetricGrid>
        <Metric label="Status" value={runQuery.data?.status ?? "pending"} />
        <Metric label="Type" value={runQuery.data?.run_type ?? "-"} />
        <Metric label="Surface" value={runQuery.data?.surface ?? "-"} />
        <Metric label="Records" value={recordsQuery.data?.items?.length ?? 0} />
      </MetricGrid>

      <div className="grid gap-6 xl:grid-cols-2">
        <JsonPanel title="Normalized">
          <CodeBlock>{JSON.stringify(recordsQuery.data?.items?.map((row) => row.data) ?? [], null, 2)}</CodeBlock>
        </JsonPanel>
        <JsonPanel title="Discovered">
          <CodeBlock>{JSON.stringify(recordsQuery.data?.items ?? [], null, 2)}</CodeBlock>
        </JsonPanel>
      </div>

      <Card className="space-y-5">
        <SectionHeader title="Promote" />
        <div className="grid gap-4 md:grid-cols-2">
          {discoveredFields.map((field) => (
            <Field key={field} label={field} hint="Output field name to save for future runs.">
              <Input
                value={mapping[field] ?? field}
                onChange={(event) => setMapping((current) => ({ ...current, [field]: event.target.value }))}
              />
            </Field>
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <Button onClick={savePromotion}>Save promoted fields</Button>
          <Button variant="secondary" onClick={() => reviewQuery.refetch()}>
            Refresh review
          </Button>
        </div>
      </Card>

      <JsonPanel title="Detail">
        <CodeBlock>{JSON.stringify(runQuery.data ?? {}, null, 2)}</CodeBlock>
      </JsonPanel>
    </div>
  );
}
