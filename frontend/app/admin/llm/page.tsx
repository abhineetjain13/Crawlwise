"use client";

import { useQuery } from "@tanstack/react-query";

import { Card } from "../../../components/ui/primitives";
import { PageHeader, SectionHeader } from "../../../components/ui/patterns";
import { api } from "../../../lib/api";

export default function AdminLlmPage() {
  const configsQuery = useQuery({ queryKey: ["llm-configs"], queryFn: api.listLlmConfigs });
  const costQuery = useQuery({ queryKey: ["llm-cost-log"], queryFn: () => api.listLlmCostLog({ limit: 20 }) });
  const configs = configsQuery.data ?? [];
  const costLogs = costQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="LLM" description="Providers, models, and budgets." />
      <Card className="space-y-4">
        <SectionHeader title="Configurations" description="Active configs resolved by task type." />
        {configs.length ? (
          <div className="overflow-auto rounded-md border border-border">
            <table className="compact-data-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Key</th>
                  <th>Daily Budget</th>
                  <th>Session Budget</th>
                  <th>Active</th>
                </tr>
              </thead>
              <tbody>
                {configs.map((config) => (
                  <tr key={config.id}>
                    <td>{config.task_type}</td>
                    <td>{config.provider}</td>
                    <td>{config.model}</td>
                    <td>{config.api_key_masked}</td>
                    <td>{config.per_domain_daily_budget_usd}</td>
                    <td>{config.global_session_budget_usd}</td>
                    <td>{config.is_active ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[13px] text-muted">No LLM configs saved yet.</p>
        )}
      </Card>

      <Card className="space-y-4">
        <SectionHeader title="Recent Usage" description="Recent task executions and token usage." />
        {costLogs.length ? (
          <div className="overflow-auto rounded-md border border-border">
            <table className="compact-data-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Domain</th>
                  <th>Input</th>
                  <th>Output</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>
                {costLogs.map((row) => (
                  <tr key={row.id}>
                    <td>{row.task_type}</td>
                    <td>{row.provider}</td>
                    <td>{row.model}</td>
                    <td>{row.domain || "--"}</td>
                    <td>{row.input_tokens}</td>
                    <td>{row.output_tokens}</td>
                    <td>{row.cost_usd}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[13px] text-muted">No LLM usage logged yet.</p>
        )}
      </Card>
    </div>
  );
}
