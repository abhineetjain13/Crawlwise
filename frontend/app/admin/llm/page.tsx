"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, PlugZap } from "lucide-react";
import { useMemo, useState } from "react";

import { Card, Button, Input, Badge } from "../../../components/ui/primitives";
import { PageHeader, SectionHeader } from "../../../components/ui/patterns";
import { cn } from "../../../lib/utils";
import { api } from "../../../lib/api";

const TASK_OPTIONS = [
  { value: "general", label: "General" },
  { value: "xpath_discovery", label: "Selector Discovery" },
  { value: "missing_field_extraction", label: "Missing Field Extraction" },
  { value: "field_cleanup_review", label: "Cleanup Review" },
] as const;

export default function AdminLlmPage() {
  const queryClient = useQueryClient();
  const catalogQuery = useQuery({ queryKey: ["llm-catalog"], queryFn: api.listLlmCatalog });
  const configsQuery = useQuery({ queryKey: ["llm-configs"], queryFn: api.listLlmConfigs });
  const costQuery = useQuery({ queryKey: ["llm-cost-log"], queryFn: () => api.listLlmCostLog({ limit: 20 }) });

  const catalog = catalogQuery.data;
  const configRows = configsQuery.data;
  const configs = useMemo(() => configRows ?? [], [configRows]);
  const costLogs = costQuery.data?.items ?? [];

  const [provider, setProvider] = useState("groq");
  const [taskType, setTaskType] = useState("general");
  const [model, setModel] = useState("");
  const [customModelEnabled, setCustomModelEnabled] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [dailyBudget, setDailyBudget] = useState("2.00");
  const [sessionBudget, setSessionBudget] = useState("10.00");
  const [testMessage, setTestMessage] = useState<string>("");
  const [testOk, setTestOk] = useState<boolean | null>(null);

  const activeProvider = useMemo(
    () => catalog?.find((item) => item.provider === provider),
    [catalog, provider],
  );
  const activeSavedConfig = useMemo(
    () => (configRows ?? []).find((item) => item.provider === provider && item.task_type === taskType && item.is_active),
    [configRows, provider, taskType],
  );
  const activeTaskConfig = useMemo(
    () => (configRows ?? []).find((item) => item.task_type === taskType && item.is_active),
    [configRows, taskType],
  );
  const hasSavedKey = Boolean(activeSavedConfig?.api_key_set);
  const hasEnvKey = Boolean(activeProvider?.api_key_set);
  const hasDraftKey = Boolean(apiKey.trim());
  const providerModels = useMemo(
    () => uniqueStrings([...(activeProvider?.recommended_models ?? []), ...configs.filter((item) => item.provider === provider).map((item) => item.model)]),
    [activeProvider?.recommended_models, configs, provider],
  );
  const effectiveModel = customModelEnabled
    ? model
    : model || activeSavedConfig?.model || activeProvider?.recommended_models?.[0] || "";
  const selectedModelValue = customModelEnabled ? "__custom__" : effectiveModel;

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
    mutationFn: ({ dailyBudgetValue, sessionBudgetValue }: { dailyBudgetValue: number; sessionBudgetValue: number }) =>
      activeTaskConfig
        ? api.updateLlmConfig(activeTaskConfig.id, {
          provider,
          model: effectiveModel,
          api_key: apiKey || undefined,
          task_type: taskType,
          per_domain_daily_budget_usd: dailyBudgetValue,
          global_session_budget_usd: sessionBudgetValue,
          is_active: true,
        })
        : api.createLlmConfig({
          provider,
          model: effectiveModel,
          api_key: apiKey || undefined,
          task_type: taskType,
          per_domain_daily_budget_usd: dailyBudgetValue,
          global_session_budget_usd: sessionBudgetValue,
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

  function handleCreateConfig() {
    const dailyBudgetValue = Number(dailyBudget.trim());
    const sessionBudgetValue = Number(sessionBudget.trim());
    if (!dailyBudget.trim() || !sessionBudget.trim()) {
      setTestOk(false);
      setTestMessage("Budgets are required.");
      return;
    }
    if (!Number.isFinite(dailyBudgetValue) || dailyBudgetValue < 0) {
      setTestOk(false);
      setTestMessage("Daily budget must be a non-negative number.");
      return;
    }
    if (!Number.isFinite(sessionBudgetValue) || sessionBudgetValue < 0) {
      setTestOk(false);
      setTestMessage("Session budget must be a non-negative number.");
      return;
    }
    if (!hasDraftKey && !hasEnvKey && !hasSavedKey) {
      setTestOk(false);
      setTestMessage("Provide an API key override or configure an env-backed key before saving.");
      return;
    }
    createMutation.mutate({ dailyBudgetValue, sessionBudgetValue });
  }

  return (
    <div className="space-y-6">
      <PageHeader title="LLM Config" />

      <Card className="space-y-6">
        <SectionHeader title="Active Configuration" description="Choose the provider and model used by LLM-dependent features. Keys stay server-side; leaving API key blank uses the env-backed provider key when available." />

        <div className="grid gap-6 md:grid-cols-3">
          <label className="grid gap-1.5 focus-within:text-accent transition-colors">
            <span className="label-caps">Provider</span>
            <select
              value={provider}
              onChange={(event) => {
                const newProvider = event.target.value;
                setProvider(newProvider);
                const p = (catalog ?? []).find((item) => item.provider === newProvider);
                setModel(p?.recommended_models?.[0] ?? "");
                setCustomModelEnabled(false);
                setTestOk(null);
                setTestMessage("");
              }}
              className="control-select focus-ring"
            >
              <option value="" disabled>Select Provider</option>
              {(catalog ?? []).map((item) => (
                <option key={item.provider} value={item.provider}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-1.5">
            <span className="label-caps">Task Context</span>
            <select value={taskType} onChange={(event) => setTaskType(event.target.value)} className="control-select focus-ring">
              {TASK_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-1.5">
            <span className="label-caps">Model</span>
            <select
              value={selectedModelValue}
              onChange={(event) => {
                const val = event.target.value;
                if (val === "__custom__") {
                  setCustomModelEnabled(true);
                  setModel("");
                } else {
                  setCustomModelEnabled(false);
                  setModel(val);
                }
                setTestOk(null);
                setTestMessage("");
              }}
              className="control-select focus-ring"
            >
              {providerModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
              <option value="__custom__">Custom (Manual ID)</option>
            </select>
          </label>

          <div className="md:col-span-3">
            {customModelEnabled && (
              <div className="mb-4">
                <span className="label-caps mb-1.5 block">Custom Model Identifier</span>
                <Input
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="e.g. meta-llama/Llama-3-70b-chat"
                />
              </div>
            )}
            
            <div className="grid gap-6 md:grid-cols-2">
              <label className="grid gap-1.5">
                <span className="label-caps">API Key Override</span>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={apiKeyPlaceholder(hasEnvKey, hasSavedKey)}
                />
              </label>

              <div className="grid grid-cols-2 gap-4">
                <label className="grid gap-1.5">
                  <span className="label-caps">Daily Budget (USD)</span>
                  <Input value={dailyBudget} onChange={(e) => setDailyBudget(e.target.value)} />
                </label>
                <label className="grid gap-1.5">
                  <span className="label-caps">Session Budget (USD)</span>
                  <Input value={sessionBudget} onChange={(e) => setSessionBudget(e.target.value)} />
                </label>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={hasEnvKey ? "success" : "warning"}>
            {hasEnvKey ? "Env Key Active" : "No Env Key"}
          </Badge>
          <Badge tone={hasSavedKey || hasDraftKey ? "success" : "warning"}>
            {savedKeyBadgeLabel(hasDraftKey, hasSavedKey)}
          </Badge>
          {activeTaskConfig ? (
            <Badge tone="success">
              Active {activeTaskConfig.provider}:{activeTaskConfig.model}
            </Badge>
          ) : null}
          {testMessage ? (
            <div className={cn("text-[13px] font-medium transition-all animate-in fade-in slide-in-from-left-2", testOk ? "text-success" : "text-danger")}>
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
            onClick={handleCreateConfig}
            disabled={createMutation.isPending || !provider || !effectiveModel}
          >
            <CheckCircle2 className="size-3.5" />
            {createMutation.isPending ? "Saving..." : "Save Configuration"}
          </Button>
        </div>
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

function apiKeyPlaceholder(hasEnvKey: boolean, hasSavedKey: boolean) {
  if (hasEnvKey) return "Env-backed key detected; leave blank to use it.";
  if (hasSavedKey) return "Saved key exists for this task; enter a new one to replace it.";
  return "Paste API key";
}

function savedKeyBadgeLabel(hasDraftKey: boolean, hasSavedKey: boolean) {
  if (hasDraftKey) return "new key entered";
  if (hasSavedKey) return "saved key ready";
  return "no saved key";
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => String(value || "").trim()).filter(Boolean)));
}
