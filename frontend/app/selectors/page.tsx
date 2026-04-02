"use client";

import { useQuery } from "@tanstack/react-query";

import { CodeBlock } from "../../components/ui/primitives";
import { JsonPanel, PageHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";

export default function SelectorsPage() {
  const { data } = useQuery({ queryKey: ["selectors"], queryFn: api.listSelectors });

  return (
    <div className="space-y-6">
      <PageHeader title="Selectors" description="Saved selector memory and defaults." />
      <JsonPanel title="Memory">
        <CodeBlock>{JSON.stringify(data ?? [], null, 2)}</CodeBlock>
      </JsonPanel>
    </div>
  );
}
