'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, PlugZap, Plus, Trash2 } from 'lucide-react';

import { Button, Dropdown, Field, Input } from '../../../components/ui/primitives';
import {
  InlineAlert,
  MutedPanelMessage,
  PageHeader,
  SectionCard,
  SurfaceSection,
} from '../../../components/ui/patterns';
import { api } from '../../../lib/api';
import type {
  LlmConfigCreatePayload,
  LlmConfigRecord,
  LlmCostLogRecord,
  LlmProviderCatalogItem,
} from '../../../lib/api/types';

const TASK_TYPES = [
  'general',
  'xpath_discovery',
  'missing_field_extraction',
  'field_cleanup_review',
  'page_classification',
  'schema_inference',
];

export default function AdminLlmPage() {
  const [providers, setProviders] = useState<LlmProviderCatalogItem[]>([]);
  const [configs, setConfigs] = useState<LlmConfigRecord[]>([]);
  const [costLog, setCostLog] = useState<LlmCostLogRecord[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [form, setForm] = useState<LlmConfigCreatePayload>({
    provider: 'groq',
    model: 'llama-3.3-70b-versatile',
    task_type: 'xpath_discovery',
    api_key: '',
    per_domain_daily_budget_usd: '0',
    global_session_budget_usd: '0',
    is_active: true,
  });

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    setError('');
    try {
      const [nextProviders, nextConfigs, nextCostLog] = await Promise.all([
        api.listLlmProviders(),
        api.listLlmConfigs(),
        api.listLlmCostLog(),
      ]);
      setProviders(nextProviders);
      setConfigs(nextConfigs);
      setCostLog(nextCostLog);
      const recommendedModel = nextProviders[0]?.recommended_models?.[0];
      if (recommendedModel) {
        setForm((current) => ({
          ...current,
          provider: nextProviders[0].provider,
          model: current.model || recommendedModel,
        }));
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load LLM settings.');
    }
  }

  async function handleSave() {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      await api.createLlmConfig(form);
      setMessage('LLM config saved.');
      setForm((current) => ({ ...current, api_key: '' }));
      await loadAll();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to save LLM config.');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setError('');
    setMessage('');
    try {
      const response = await api.testLlmConnection({
        provider: form.provider,
        model: form.model,
        api_key: form.api_key,
      });
      setMessage(response.message);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Connection test failed.');
    } finally {
      setTesting(false);
    }
  }

  async function handleDelete(configId: number) {
    setError('');
    setMessage('');
    try {
      await api.deleteLlmConfig(configId);
      setMessage('LLM config removed.');
      await loadAll();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to delete LLM config.');
    }
  }

  const recommendedModels =
    providers.find((provider) => provider.provider === form.provider)?.recommended_models ?? [];

  return (
    <div className="page-stack">
      <PageHeader
        title="LLM Config"
        description="Restore runtime provider control for selector suggestion, cleanup review, and extraction fallback tasks."
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="page-stack">
          <SectionCard
            title="Create Config"
            description="Activate one provider/model per task. New active configs automatically replace the previous active config for the same task."
            className="space-y-5"
          >
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Provider">
                <Dropdown<string>
                  value={form.provider}
                  onChange={(provider) => {
                    const nextModel =
                      providers.find((row) => row.provider === provider)?.recommended_models?.[0] ??
                      '';
                    setForm((current) => ({
                      ...current,
                      provider,
                      model: nextModel || current.model,
                    }));
                  }}
                  options={providers.map((provider) => ({
                    value: provider.provider,
                    label: provider.label,
                  }))}
                />
              </Field>

              <Field label="Task">
                <Dropdown<string>
                  value={form.task_type}
                  onChange={(task_type) => setForm((current) => ({ ...current, task_type }))}
                  options={TASK_TYPES.map((taskType) => ({ value: taskType, label: taskType }))}
                />
              </Field>

              <Field label="Model" className="md:col-span-2">
                <Input
                  value={form.model}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, model: event.target.value }))
                  }
                  list="llm-model-suggestions"
                />
                <datalist id="llm-model-suggestions">
                  {recommendedModels.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </Field>

              <Field label="API Key" className="md:col-span-2">
                <Input
                  type="password"
                  value={form.api_key ?? ''}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, api_key: event.target.value }))
                  }
                  placeholder="Leave blank to rely on environment variables."
                />
              </Field>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => void handleTest()}
                disabled={testing}
              >
                <PlugZap className="size-3.5" />
                {testing ? 'Testing...' : 'Test Connection'}
              </Button>
              <Button
                type="button"
                variant="accent"
                onClick={() => void handleSave()}
                disabled={saving || !form.model.trim()}
              >
                <Plus className="size-3.5" />
                {saving ? 'Saving...' : 'Save Config'}
              </Button>
            </div>

            {message ? <InlineAlert message={message} tone="neutral" /> : null}
            {error ? <InlineAlert message={error} tone="danger" /> : null}
          </SectionCard>

          <SectionCard
            title="Active Configs"
            description="The active runtime snapshot available to selector discovery and cleanup tasks."
            className="space-y-4"
          >
            {configs.length ? (
              <div className="space-y-3">
                {configs.map((config) => (
                  <div
                    key={config.id}
                    className="border-border bg-background-elevated rounded-[var(--radius-lg)] border p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <div className="text-foreground text-sm font-medium">
                            {config.task_type}
                          </div>
                          {config.is_active ? (
                            <div className="bg-success-bg text-success inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium">
                              <CheckCircle2 className="size-3.5" />
                              active
                            </div>
                          ) : null}
                        </div>
                        <div className="text-muted text-sm font-normal">
                          {config.provider} · {config.model}
                        </div>
                        <div className="text-muted text-sm font-normal">
                          {config.api_key_set ? config.api_key_masked : 'env-backed or unset'}
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="danger"
                        size="icon"
                        onClick={() => void handleDelete(config.id)}
                        aria-label="Delete config"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <MutedPanelMessage title="No configs saved" description="No LLM configs saved yet." />
            )}
          </SectionCard>
        </div>
        <div className="page-stack">
          <SectionCard
            title="Recent Cost Log"
            description="Latest LLM usage events recorded by the backend runtime."
            className="flex-1"
          >
            {costLog.length ? (
              <div className="custom-scrollbar max-h-[700px] overflow-x-auto overflow-y-auto">
                <table className="w-full min-w-[850px] table-fixed border-collapse text-left">
                  <thead>
                    <tr className="border-divider/50 border-b">
                      <th className="text-muted w-[140px] px-0 py-3 text-xs font-bold tracking-[0.1em] uppercase">
                        Usage & Cost
                      </th>
                      <th className="text-muted w-[180px] px-4 py-3 text-xs font-bold tracking-[0.1em] uppercase">
                        Task Type
                      </th>
                      <th className="text-muted w-[200px] px-4 py-3 text-xs font-bold tracking-[0.1em] uppercase">
                        Target Entity
                      </th>
                      <th className="text-muted px-4 py-3 text-xs font-bold tracking-[0.1em] uppercase">
                        Provider / Model
                      </th>
                      <th className="text-muted w-[90px] px-0 py-3 text-right text-xs font-bold tracking-[0.1em] uppercase">
                        Time
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-divider/20 divide-y">
                    {costLog.slice(0, 40).map((entry) => {
                      const totalTokens = entry.input_tokens + entry.output_tokens;
                      const cost = parseFloat(entry.cost_usd);
                      return (
                        <tr
                          key={entry.id}
                          className="hover:bg-accent/[0.04] group transition-colors"
                        >
                          <td className="px-0 py-4">
                            <div className="flex flex-col">
                              <div className="flex items-baseline gap-1.5">
                                <span className="text-foreground text-sm leading-none font-medium tabular-nums">
                                  {totalTokens.toLocaleString()}
                                </span>
                                <span className="text-muted text-sm font-normal">tokens</span>
                              </div>
                              <span className="text-accent mt-1 font-mono text-sm leading-none font-medium">
                                ${cost > 0 && cost < 0.0001 ? cost.toFixed(6) : cost.toFixed(4)}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-4">
                            <span className="text-foreground text-sm leading-normal font-medium">
                              {entry.task_type.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td className="px-4 py-4">
                            <div
                              className="text-foreground/80 truncate text-sm font-normal"
                              title={entry.domain || `Run #${entry.run_id}`}
                            >
                              {entry.domain || (entry.run_id ? `Run #${entry.run_id}` : 'system')}
                            </div>
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex flex-col overflow-hidden leading-tight">
                              <span className="text-foreground truncate text-sm font-medium">
                                {entry.provider}
                              </span>
                              <span
                                className="text-muted truncate text-sm font-normal"
                                title={entry.model}
                              >
                                {entry.model}
                              </span>
                            </div>
                          </td>
                          <td className="px-0 py-4 text-right">
                            <span className="text-muted group-hover:text-foreground text-sm font-normal transition-colors">
                              {new Date(entry.created_at).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                                hour12: false,
                              })}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-12 text-center">
                <MutedPanelMessage
                  title="No cost events"
                  description="Detailed LLM usage and token metrics will appear here once active."
                />
              </div>
            )}
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
