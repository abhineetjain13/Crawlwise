"use client";

import { useQuery } from "@tanstack/react-query";

import { CodeBlock } from "../../../components/ui/primitives";
import { JsonPanel, PageHeader } from "../../../components/ui/patterns";
import { api } from "../../../lib/api";

export default function AdminLlmPage() {
  const { data } = useQuery({ queryKey: ["llm-configs"], queryFn: api.listLlmConfigs });

  return (
    <div className="space-y-6">
      <PageHeader title="LLM" description="Providers, models, and budgets." />
      <JsonPanel title="Configurations">
        <CodeBlock>{JSON.stringify(data ?? [], null, 2)}</CodeBlock>
      </JsonPanel>
    </div>
  );
}
