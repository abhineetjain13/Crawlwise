"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, PlugZap } from "lucide-react";
import { useMemo, useState } from "react";

import { Card, Button, Input, Badge } from "../../../components/ui/primitives";
import { PageHeader, SectionHeader } from "../../../components/ui/patterns";
import { api } from "../../../lib/api";

const TASK_OPTIONS = [
  { value: "general", label: "General" },
  { value: "xpath_discovery", label: "Selector Discovery" },
  { value: "missing_field_extraction", label: "Missing Field Extraction" },
] as const;

export default function AdminLlmPage() {
  const queryClient = useQueryClient();
  const catalogQuery = useQuery({ queryKey: ["llm-catalog"], queryFn: api.listLlmCatalog });
  const configsQuery = useQuery({ queryKey: ["llm-configs"], queryFn: api.listLlmConfigs });
  const costQuery = useQuery({ queryKey: ["llm-cost-log"], queryFn: () => api.listLlmCostLog({ limit: 20 }) });

  const catalog = catalogQuery.data;
  const configs = configsQuery.data ?? [];
  const costLogs = costQuery.data?.items ?? [];

  const [provider, setProvider] = useState("groq");
  const [taskType, setTaskType] = useState("general");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [dailyBudget, setDailyBudget] = useState("2.00");
  const [sessionBudget, setSessionBudget] = useState("10.00");
  const [testMessage, setTestMessage] = useState<string>("");
  const [testOk, setTestOk] = useState<boolean | null>(null);

  const activeProvider = useMemo(
    () => catalog?.find((item) => item.provider === provider),
    [catalog, provider],
  );
  const effectiveModel = model || activeProvider?.recommended_models?.[0] || "";

  const testMutation = useMutation({
    mutationFn: () => api.testLlmConnection({ provider, model: effectiveModel, api_key: apiKey || undefined }),
    onSuccess: (result) => {
      setTestOk(result.ok);
      setTestMessage(result.message);
    },
    onError: (error) => {
      setTestOk(false);
      setTestMessage(error instanceof Error ? error.message : "Connection test failed.");
    },
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.createLlmConfig({
        provider,
        model: effectiveModel,
        api_key: apiKey || undefined,
        task_type: taskType,
        per_domain_daily_budget_usd: dailyBudget,
        global_session_budget_usd: sessionBudget,
      }),
    onSuccess: () => {
      setApiKey("");
      setTestOk(null);
      setTestMessage("");
      void queryClient.invalidateQueries({ queryKey: ["llm-configs"] });
    },
    onError: (error) => {
      setTestOk(false);
      setTestMessage(error instanceof Error ? error.message : "Failed to save configuration.");
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader title="LLM Config" />

      <Card className="mx-auto max-w-[760px] space-y-5">
        <SectionHeader title="Active Configuration" description="Choose the provider and model used by LLM-dependent features. Keys stay server-side; leaving API key blank uses the env-backed provider key when available." />

        <div className="grid gap-4 md:grid-cols-2">
          <label className="grid gap-1.5">
            <span className="label-caps">Provider</span>
            <select
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value);
                const next = (catalog ?? []).find((item) => item.provider === event.target.value);
                setModel(next?.recommended_models?.[0] ?? "");
                setTestOk(null);
                setTestMessage("");
              }}
              className="control-select focus-ring"
            >
              {(catalog ?? []).map((item) => (
                <option key={item.provider} value={item.provider}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-1.5">
            <span className="label-caps">Task Type</span>
            <select value={taskType} onChange={(event) => setTaskType(event.target.value)} className="control-select focus-ring">
              {TASK_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-1.5 md:col-span-2">
            <span className="label-caps">Model</span>
            <Input
              value={effectiveModel}
              onChange={(event) => {
                setModel(event.target.value);
                setTestOk(null);
                setTestMessage("");
              }}
              placeholder="llama-3.1-8b-instant"
            />
            {activeProvider?.recommended_models?.length ? (
              <div className="flex flex-wrap gap-2">
                {activeProvider.recommended_models.map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => {
                      setModel(value);
                      setTestOk(null);
                      setTestMessage("");
                    }}
                    className="rounded-[var(--radius-sm)] border border-border px-2 py-1 text-[12px] text-muted transition hover:bg-background-elevated hover:text-foreground"
                  >
                    {value}
                  </button>
                ))}
              </div>
            ) : null}
          </label>

          <label className="grid gap-1.5 md:col-span-2">
            <span className="label-caps">API Key Override</span>
            <Input
              type="password"
              value={apiKey}
              onChange={(event) => {
                setApiKey(event.target.value);
                setTestOk(null);
                setTestMessage("");
              }}
              placeholder={activeProvider?.api_key_set ? "Env-backed key detected; leave blank to use it." : "Paste API key"}
            />
          </label>

          <label className="grid gap-1.5">
            <span className="label-caps">Daily Budget (USD)</span>
            <Input value={dailyBudget} onChange={(event) => setDailyBudget(event.target.value)} inputMode="decimal" />
          </label>

          <label className="grid gap-1.5">
            <span className="label-caps">Session Budget (USD)</span>
            <Input value={sessionBudget} onChange={(event) => setSessionBudget(event.target.value)} inputMode="decimal" />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={activeProvider?.api_key_set ? "success" : "warning"}>
            {activeProvider?.api_key_set ? "env key ready" : "env key missing"}
          </Badge>
          {testMessage ? (
            <div className={testOk ? "text-[13px] text-success" : "text-[13px] text-danger"}>
              {testMessage}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="secondary" onClick={() => testMutation.mutate()} disabled={testMutation.isPending || !provider || !effectiveModel}>
            <PlugZap className="size-3.5" />
            {testMutation.isPending ? "Testing..." : "Test Connection"}
          </Button>
          <Button
            type="button"
            variant="accent"
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending || !provider || !effectiveModel || testOk !== true}
          >
            <CheckCircle2 className="size-3.5" />
            {createMutation.isPending ? "Saving..." : "Save Configuration"}
          </Button>
        </div>
      </Card>

      <Card className="space-y-4">
        <SectionHeader title="Saved Configs" description="Saved provider assignments by task type. Keys are masked and never returned to the client." />
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
          <p className="text-[13px] text-muted">No saved configs yet.</p>
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
