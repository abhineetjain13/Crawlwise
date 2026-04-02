"use client";

import { useQuery } from "@tanstack/react-query";

import { CodeBlock } from "../../components/ui/primitives";
import { JsonPanel, PageHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";

export default function JobsPage() {
  const { data } = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs, refetchInterval: 5000 });

  return (
    <div className="space-y-6">
      <PageHeader title="Jobs" description="Live worker state." />
      <JsonPanel title="Jobs">
        <CodeBlock>{JSON.stringify(data ?? [], null, 2)}</CodeBlock>
      </JsonPanel>
    </div>
  );
}
