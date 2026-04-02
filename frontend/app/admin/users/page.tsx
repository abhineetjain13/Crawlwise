"use client";

import { useQuery } from "@tanstack/react-query";

import { CodeBlock } from "../../../components/ui/primitives";
import { JsonPanel, PageHeader } from "../../../components/ui/patterns";
import { api } from "../../../lib/api";

export default function AdminUsersPage() {
  const { data } = useQuery({ queryKey: ["users"], queryFn: api.listUsers });

  return (
    <div className="space-y-6">
      <PageHeader title="Users" description="Accounts and roles." />
      <JsonPanel title="List">
        <CodeBlock>{JSON.stringify(data?.items ?? [], null, 2)}</CodeBlock>
      </JsonPanel>
    </div>
  );
}
