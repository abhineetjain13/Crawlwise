'use client';

import { RefreshCcw, Pencil, Save, Search, Trash2, X } from 'lucide-react';
import { useDeferredValue, useEffect, useEffectEvent, useMemo, useState } from 'react';

import {
  DataRegionEmpty,
  DataRegionLoading,
  DetailRow,
  EmptyPanel,
  InlineAlert,
  KVTile,
  MutedPanelMessage,
  NavList,
  PageHeader,
  SurfacePanel,
  SurfaceSection,
  TabBar,
} from '../../../components/ui/patterns';
import { Badge, Button, Dropdown, Input, Toggle } from '../../../components/ui/primitives';
import { api } from '../../../lib/api';
import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfile,
  DomainRunProfileRecord,
  SelectorDomainSummary,
  SelectorRecord,
  SelectorUpdatePayload,
} from '../../../lib/api/types';
import { getNormalizedDomain, isSpecialUseDomain } from '../../../lib/format/domain';

type LocalRecord = SelectorRecord & { _uid: string };

type EditDraft = {
  field_name: string;
  kind: 'xpath' | 'css_selector' | 'regex';
  selectorValue: string;
  source: string;
  is_active: boolean;
};

type SurfaceWorkspace = {
  surface: string;
  selectorCount: number;
  selectors: LocalRecord[];
  profile: DomainRunProfileRecord | null;
  learning: DomainFieldFeedbackRecord[];
  completedRuns: CrawlRun[];
};

type DomainWorkspace = {
  domain: string;
  surfaces: SurfaceWorkspace[];
  cookieMemory: DomainCookieMemoryRecord | null;
  learning: DomainFieldFeedbackRecord[];
  completedRunCount: number;
  latestCompletedAt: string | null;
};

function surfaceLabel(surface: string) {
  if (surface === 'ecommerce_listing') return 'Commerce Listing';
  if (surface === 'ecommerce_detail') return 'Commerce Detail';
  if (surface === 'job_listing') return 'Job Listing';
  if (surface === 'job_detail') return 'Job Detail';
  return surface.replace(/_/g, ' ');
}

function titleCaseToken(value: string | null | undefined) {
  return String(value || '')
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
    .join(' ');
}

function selectorValue(record: Pick<SelectorRecord, 'xpath' | 'css_selector' | 'regex'>) {
  return record.xpath ?? record.css_selector ?? record.regex ?? '';
}

function profileSearchText(profile: DomainRunProfileRecord) {
  return [
    profile.domain,
    profile.surface,
    profile.profile.fetch_profile.fetch_mode,
    profile.profile.fetch_profile.extraction_source,
    profile.profile.fetch_profile.js_mode,
    profile.profile.fetch_profile.traversal_mode,
    profile.profile.locality_profile.geo_country,
    profile.profile.locality_profile.language_hint ?? '',
    profile.profile.locality_profile.currency_hint ?? '',
  ]
    .join(' ')
    .toLowerCase();
}

function defaultDomainRunProfile(): DomainRunProfile {
  return {
    version: 1,
    fetch_profile: {
      fetch_mode: 'auto',
      extraction_source: 'raw_html',
      js_mode: 'auto',
      include_iframes: false,
      traversal_mode: null,
      request_delay_ms: 500,
    },
    locality_profile: {
      geo_country: 'auto',
      language_hint: null,
      currency_hint: null,
    },
    diagnostics_profile: {
      capture_html: true,
      capture_screenshot: false,
      capture_network: 'matched_only',
      capture_response_headers: true,
      capture_browser_diagnostics: true,
    },
    acquisition_contract: {
      preferred_browser_engine: 'auto',
      prefer_browser: false,
      prefer_curl_handoff: false,
      handoff_cookie_engine: 'auto',
      last_quality_success: null,
      stale_after_failures: {
        failure_count: 0,
        stale: false,
      },
    },
    source_run_id: null,
    saved_at: null,
  };
}

function cloneDomainRunProfile(profile: DomainRunProfile | null | undefined): DomainRunProfile {
  const base = defaultDomainRunProfile();
  if (!profile) {
    return base;
  }
  return {
    version: 1,
    fetch_profile: {
      ...base.fetch_profile,
      ...(profile.fetch_profile ?? {}),
    },
    locality_profile: {
      ...base.locality_profile,
      ...(profile.locality_profile ?? {}),
    },
    diagnostics_profile: {
      ...base.diagnostics_profile,
      ...(profile.diagnostics_profile ?? {}),
    },
    acquisition_contract: {
      ...base.acquisition_contract,
      ...(profile.acquisition_contract ?? {}),
      stale_after_failures: {
        ...base.acquisition_contract.stale_after_failures,
        ...(profile.acquisition_contract?.stale_after_failures ?? {}),
      },
    },
    source_run_id: profile.source_run_id ?? null,
    saved_at: profile.saved_at ?? null,
  };
}

function profileDraftKey(domain: string, surface: string) {
  return `${domain}:${surface}`;
}

function feedbackSearchText(feedback: DomainFieldFeedbackRecord) {
  return [
    feedback.domain,
    feedback.surface,
    feedback.field_name,
    feedback.action,
    feedback.source_kind,
    feedback.source_value ?? '',
    feedback.selector_kind ?? '',
    feedback.selector_value ?? '',
  ]
    .join(' ')
    .toLowerCase();
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) {
    return '—';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return parsed.toLocaleString();
}

function isInternalDomainMemoryArtifact(
  domain: string,
  surfaceCount: number,
  hasCookieMemory: boolean,
  learningCount: number,
  completedRunCount: number,
) {
  const normalized = String(domain || '')
    .trim()
    .toLowerCase();
  if (!normalized.startsWith('owned-session-')) {
    return false;
  }
  return hasCookieMemory && surfaceCount === 0 && learningCount === 0 && completedRunCount === 0;
}

function DomainMemoryWorkspaceLoading() {
  return (
    <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
      <SurfacePanel className="flex max-h-[calc(100vh-180px)] flex-col space-y-3 p-3">
        <div className="flex shrink-0 items-center justify-between px-1">
          <h3 className="type-label">Domains</h3>
          <span className="text-muted text-xs">—</span>
        </div>
        <DataRegionLoading count={6} className="px-0 py-0" />
      </SurfacePanel>
      <div className="space-y-4">
        <SurfacePanel className="space-y-4 p-4">
          <DataRegionLoading count={2} className="px-0 py-0" />
        </SurfacePanel>
        <SurfacePanel className="p-4">
          <DataRegionLoading count={8} className="px-0 py-0" />
        </SurfacePanel>
      </div>
    </div>
  );
}

export default function DomainMemoryManagePage() {
  const [records, setRecords] = useState<LocalRecord[]>([]);
  const [selectorSummaries, setSelectorSummaries] = useState<SelectorDomainSummary[]>([]);
  const [profiles, setProfiles] = useState<DomainRunProfileRecord[]>([]);
  const [cookies, setCookies] = useState<DomainCookieMemoryRecord[]>([]);
  const [feedback, setFeedback] = useState<DomainFieldFeedbackRecord[]>([]);
  const [completedRuns, setCompletedRuns] = useState<CrawlRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectorLoading, setSelectorLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedDomain, setSelectedDomain] = useState('');
  const [loadedSelectorDomain, setLoadedSelectorDomain] = useState('');
  const [selectorRefreshKey, setSelectorRefreshKey] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [surfaceFilter, setSurfaceFilter] = useState('all');
  const [activeTab, setActiveTab] = useState('selectors');
  const [profileDrafts, setProfileDrafts] = useState<Record<string, DomainRunProfile>>({});
  const [profileSaveKey, setProfileSaveKey] = useState('');
  const deferredSearchQuery = useDeferredValue(searchQuery);

  function toLocalRecords(selectorData: SelectorRecord[]) {
    return selectorData.map((record, index) => ({
      ...record,
      _uid: `${record.id}-${index}-${Date.now()}`,
    }));
  }

  async function loadWorkspace(showLoading = true) {
    if (showLoading) {
      setLoading(true);
    }
    setError('');
    try {
      const [selectorSummaryData, profileData, cookieData, feedbackData, crawlData] =
        await Promise.all([
          api.listSelectorSummaries(),
          api.listDomainRunProfiles(),
          api.listDomainCookieMemory(),
          api.listDomainFieldFeedback({ limit: 100 }),
          api.listCrawls({ status: 'completed', limit: 100 }),
        ]);
      setSelectorSummaries(selectorSummaryData);
      setProfiles(profileData);
      setCookies(cookieData);
      setFeedback(feedbackData);
      setCompletedRuns(crawlData.items);
      setRecords([]);
      setLoadedSelectorDomain('');
      setSelectorRefreshKey((current) => current + 1);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load domain memory.');
    } finally {
      setLoading(false);
    }
  }

  const loadWorkspaceOnMount = useEffectEvent(() => {
    void loadWorkspace(false);
  });

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      loadWorkspaceOnMount();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  const availableSurfaces = useMemo(() => {
    return Array.from(
      new Set([
        ...selectorSummaries.map((summary) => summary.surface),
        ...records.map((record) => record.surface),
        ...profiles.map((profile) => profile.surface),
        ...feedback.map((entry) => entry.surface),
        ...completedRuns.map((run) => run.surface),
      ]),
    ).sort();
  }, [completedRuns, feedback, profiles, records, selectorSummaries]);

  const groupedWorkspaces = useMemo<DomainWorkspace[]>(() => {
    const query = deferredSearchQuery.trim().toLowerCase();
    const byDomain = new Map<string, Map<string, SurfaceWorkspace>>();
    const cookiesByDomain = new Map(cookies.map((row) => [row.domain, row] as const));
    const runsByDomain = new Map<string, Map<string, CrawlRun[]>>();

    function ensureSurfaceWorkspace(domain: string, surface: string): SurfaceWorkspace {
      const domainEntry = byDomain.get(domain) ?? new Map<string, SurfaceWorkspace>();
      if (!byDomain.has(domain)) {
        byDomain.set(domain, domainEntry);
      }
      const existing = domainEntry.get(surface);
      if (existing) {
        return existing;
      }
      const created: SurfaceWorkspace = {
        surface,
        selectorCount: 0,
        selectors: [],
        profile: null,
        learning: [],
        completedRuns: [],
      };
      domainEntry.set(surface, created);
      return created;
    }

    function ensureDomainRuns(domain: string, surface: string) {
      const domainEntry = runsByDomain.get(domain) ?? new Map<string, CrawlRun[]>();
      if (!runsByDomain.has(domain)) {
        runsByDomain.set(domain, domainEntry);
      }
      const existing = domainEntry.get(surface);
      if (existing) {
        return existing;
      }
      const created: CrawlRun[] = [];
      domainEntry.set(surface, created);
      return created;
    }

    for (const summary of selectorSummaries) {
      if (surfaceFilter !== 'all' && summary.surface !== surfaceFilter) {
        continue;
      }
      const searchable = [summary.domain, summary.surface].join(' ').toLowerCase();
      if (query && !searchable.includes(query) && !summary.domain.toLowerCase().includes(query)) {
        continue;
      }
      ensureSurfaceWorkspace(summary.domain, summary.surface).selectorCount =
        summary.selector_count;
    }

    for (const record of records) {
      if (surfaceFilter !== 'all' && record.surface !== surfaceFilter) {
        continue;
      }
      const searchable = [
        record.domain,
        record.surface,
        record.field_name,
        record.source,
        selectorValue(record),
      ]
        .join(' ')
        .toLowerCase();
      if (query && !searchable.includes(query) && !record.domain.toLowerCase().includes(query)) {
        continue;
      }
      const workspace = ensureSurfaceWorkspace(record.domain, record.surface);
      workspace.selectors.push(record);
      workspace.selectorCount = Math.max(workspace.selectorCount, workspace.selectors.length);
    }

    for (const profile of profiles) {
      if (surfaceFilter !== 'all' && profile.surface !== surfaceFilter) {
        continue;
      }
      if (
        query &&
        !profileSearchText(profile).includes(query) &&
        !profile.domain.toLowerCase().includes(query)
      ) {
        continue;
      }
      ensureSurfaceWorkspace(profile.domain, profile.surface).profile = profile;
    }

    for (const row of feedback) {
      if (surfaceFilter !== 'all' && row.surface !== surfaceFilter) {
        continue;
      }
      if (
        query &&
        !feedbackSearchText(row).includes(query) &&
        !row.domain.toLowerCase().includes(query)
      ) {
        continue;
      }
      ensureSurfaceWorkspace(row.domain, row.surface).learning.push(row);
    }

    for (const run of completedRuns) {
      const domain =
        String(run.result_summary?.domain || '').trim() || getNormalizedDomain(run.url);
      if (!domain || isSpecialUseDomain(domain)) {
        continue;
      }
      if (surfaceFilter !== 'all' && run.surface !== surfaceFilter) {
        continue;
      }
      const searchable = [domain, run.surface, run.url, run.status].join(' ').toLowerCase();
      if (query && !searchable.includes(query) && !domain.toLowerCase().includes(query)) {
        continue;
      }
      ensureDomainRuns(domain, run.surface).push(run);
      ensureSurfaceWorkspace(domain, run.surface).completedRuns.push(run);
    }

    const visibleDomains = new Set<string>([
      ...byDomain.keys(),
      ...runsByDomain.keys(),
      ...cookies
        .filter((row) => {
          if (!query) {
            return surfaceFilter === 'all';
          }
          return row.domain.toLowerCase().includes(query);
        })
        .map((row) => row.domain),
    ]);

    const workspaces: DomainWorkspace[] = [];
    for (const domain of visibleDomains) {
      const normalizedDomain = String(domain || '').trim();
      if (!normalizedDomain || isSpecialUseDomain(normalizedDomain)) {
        continue;
      }
      const surfaces = Array.from(
        (byDomain.get(domain) ?? new Map<string, SurfaceWorkspace>()).values(),
      ).sort((left, right) => left.surface.localeCompare(right.surface));
      const completedRunCount = surfaces.reduce(
        (count, surface) => count + surface.completedRuns.length,
        0,
      );
      const latestCompletedAt =
        surfaces
          .flatMap((surface) => surface.completedRuns)
          .map((run) => run.completed_at ?? run.updated_at ?? run.created_at)
          .filter(Boolean)
          .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0] ?? null;
      const cookieMemory = cookiesByDomain.get(domain) ?? null;
      const learning = surfaces.flatMap((surface) => surface.learning);
      if (
        isInternalDomainMemoryArtifact(
          normalizedDomain,
          surfaces.length,
          Boolean(cookieMemory),
          learning.length,
          completedRunCount,
        )
      ) {
        continue;
      }
      if (!surfaces.length && !cookieMemory) {
        continue;
      }
      workspaces.push({
        domain,
        surfaces,
        cookieMemory,
        learning,
        completedRunCount,
        latestCompletedAt,
      });
    }

    return workspaces.sort((left, right) => {
      const completedDelta = right.completedRunCount - left.completedRunCount;
      if (completedDelta !== 0) {
        return completedDelta;
      }
      const leftTime = left.latestCompletedAt ? new Date(left.latestCompletedAt).getTime() : 0;
      const rightTime = right.latestCompletedAt ? new Date(right.latestCompletedAt).getTime() : 0;
      if (rightTime !== leftTime) {
        return rightTime - leftTime;
      }
      const leftMemoryScore =
        left.surfaces.reduce((count, surface) => count + surface.selectorCount, 0) +
        left.surfaces.filter((surface) => surface.profile).length +
        left.learning.length +
        (left.cookieMemory ? 1 : 0);
      const rightMemoryScore =
        right.surfaces.reduce((count, surface) => count + surface.selectorCount, 0) +
        right.surfaces.filter((surface) => surface.profile).length +
        right.learning.length +
        (right.cookieMemory ? 1 : 0);
      if (rightMemoryScore !== leftMemoryScore) {
        return rightMemoryScore - leftMemoryScore;
      }
      return left.domain.localeCompare(right.domain);
    });
  }, [
    completedRuns,
    cookies,
    deferredSearchQuery,
    feedback,
    profiles,
    records,
    selectorSummaries,
    surfaceFilter,
  ]);

  const resolvedSelectedDomain =
    selectedDomain && groupedWorkspaces.some((entry) => entry.domain === selectedDomain)
      ? selectedDomain
      : (groupedWorkspaces[0]?.domain ?? '');

  const selectedWorkspace =
    groupedWorkspaces.find((entry) => entry.domain === resolvedSelectedDomain) ??
    groupedWorkspaces[0] ??
    null;

  useEffect(() => {
    if (!resolvedSelectedDomain) {
      return;
    }
    let cancelled = false;
    async function loadSelectedDomainSelectors() {
      setSelectorLoading(true);
      try {
        const selectorData = await api.listSelectors({ domain: resolvedSelectedDomain });
        if (cancelled) {
          return;
        }
        setRecords(toLocalRecords(selectorData));
        setLoadedSelectorDomain(resolvedSelectedDomain);
      } catch (nextError) {
        if (cancelled) {
          return;
        }
        setError(nextError instanceof Error ? nextError.message : 'Unable to load selectors.');
      } finally {
        if (!cancelled) {
          setSelectorLoading(false);
        }
      }
    }
    void loadSelectedDomainSelectors();
    return () => {
      cancelled = true;
    };
  }, [resolvedSelectedDomain, selectorRefreshKey]);

  function startEdit(record: LocalRecord) {
    setEditingId(record._uid);
    setDraft({
      field_name: record.field_name,
      kind: record.xpath ? 'xpath' : record.css_selector ? 'css_selector' : 'regex',
      selectorValue: selectorValue(record),
      source: record.source,
      is_active: record.is_active,
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft(null);
  }

  async function saveEdit(record: LocalRecord) {
    if (!draft) {
      return;
    }
    const payload: SelectorUpdatePayload = {
      field_name: draft.field_name,
      xpath: draft.kind === 'xpath' ? draft.selectorValue : null,
      css_selector: draft.kind === 'css_selector' ? draft.selectorValue : null,
      regex: draft.kind === 'regex' ? draft.selectorValue : null,
      source: draft.source,
      is_active: draft.is_active,
    };
    try {
      const updated = await api.updateSelector(record.id, payload);
      setRecords((current) =>
        current.map((entry) =>
          entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry,
        ),
      );
      cancelEdit();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to save selector.');
    }
  }

  async function toggleActive(record: LocalRecord) {
    try {
      const updated = await api.updateSelector(record.id, { is_active: !record.is_active });
      setRecords((current) =>
        current.map((entry) =>
          entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry,
        ),
      );
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to update selector state.');
    }
  }

  async function deleteRecord(record: LocalRecord) {
    try {
      await api.deleteSelector(record.id);
      setRecords((current) => current.filter((entry) => entry._uid !== record._uid));
      setSelectorSummaries((current) =>
        current.map((entry) =>
          entry.domain === record.domain && entry.surface === record.surface
            ? { ...entry, selector_count: Math.max(0, entry.selector_count - 1) }
            : entry,
        ),
      );
      if (editingId === record._uid) {
        cancelEdit();
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to delete selector.');
    }
  }

  async function deleteDomainSelectors(domain: string) {
    try {
      await api.deleteSelectorsByDomain(domain);
      let removedEditingRecord = false;
      setRecords((current) => {
        const editingRecord =
          editingId === null ? null : current.find((record) => record._uid === editingId);
        removedEditingRecord = editingRecord?.domain === domain;
        return current.filter((entry) => entry.domain !== domain);
      });
      if (removedEditingRecord) {
        cancelEdit();
      }
      setSelectorSummaries((current) => current.filter((entry) => entry.domain !== domain));
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : 'Unable to clear domain selectors.',
      );
    }
  }

  function profileDraftFor(domain: string, surfaceWorkspace: SurfaceWorkspace) {
    const key = profileDraftKey(domain, surfaceWorkspace.surface);
    return profileDrafts[key] ?? cloneDomainRunProfile(surfaceWorkspace.profile?.profile);
  }

  function updateProfileDraft(
    domain: string,
    surfaceWorkspace: SurfaceWorkspace,
    updater: (current: DomainRunProfile) => DomainRunProfile,
  ) {
    setError('');
    const key = profileDraftKey(domain, surfaceWorkspace.surface);
    setProfileDrafts((current) => ({
      ...current,
      [key]: updater(current[key] ?? cloneDomainRunProfile(surfaceWorkspace.profile?.profile)),
    }));
  }

  function latestCompletedRunId(surfaceWorkspace: SurfaceWorkspace) {
    const latestRun = [...surfaceWorkspace.completedRuns].sort((left, right) => {
      const leftTime = new Date(left.completed_at ?? left.updated_at ?? left.created_at).getTime();
      const rightTime = new Date(
        right.completed_at ?? right.updated_at ?? right.created_at,
      ).getTime();
      return rightTime - leftTime;
    })[0];
    return latestRun?.id ?? null;
  }

  async function saveProfile(domain: string, surfaceWorkspace: SurfaceWorkspace) {
    const sourceRunId = latestCompletedRunId(surfaceWorkspace);
    if (!sourceRunId) {
      setError('No completed run available to save this profile.');
      return;
    }
    const saveKey = profileDraftKey(domain, surfaceWorkspace.surface);
    setProfileSaveKey(saveKey);
    setError('');
    try {
      await api.saveDomainRunProfile(sourceRunId, {
        profile: profileDraftFor(domain, surfaceWorkspace),
      });
      setProfileDrafts((current) => {
        const next = { ...current };
        delete next[saveKey];
        return next;
      });
      await loadWorkspace(false);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to save run profile.');
    } finally {
      setProfileSaveKey('');
    }
  }
  return (
    <div className="page-stack-lg">
      <PageHeader
        title="Domain Memory"
        description="Manage learned selectors, run profiles, cookies, and recent learning by domain."
        actions={
          <Button
            type="button"
            variant="secondary"
            className="h-[var(--control-height)]"
            onClick={() => void loadWorkspace()}
            disabled={loading}
          >
            <RefreshCcw className="size-3.5" />
            {loading ? 'Refreshing...' : 'Refresh'}
          </Button>
        }
      />

      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative min-w-0 flex-1">
          <Input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search domain, field, selector text, fetch mode, or feedback"
          />
        </div>
        <Dropdown<string>
          value={surfaceFilter}
          onChange={setSurfaceFilter}
          options={[
            { value: 'all', label: 'All surfaces' },
            ...availableSurfaces.map((surface) => ({
              value: surface,
              label: surfaceLabel(surface),
            })),
          ]}
        />
      </div>

      {error ? <InlineAlert message={error} /> : null}

      {loading ? (
        <DomainMemoryWorkspaceLoading />
      ) : !groupedWorkspaces.length ? (
        <EmptyPanel
          title="No domain memory found"
          description="Run a crawl, save selectors, or keep learning signals to populate this workspace."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
          {/* ── Domain sidebar ── */}
          <SurfacePanel className="flex max-h-[calc(100vh-180px)] flex-col space-y-3 p-3">
            <div className="flex shrink-0 items-center justify-between px-1">
              <h3 className="type-label">Domains</h3>
              <span className="text-muted text-xs">{groupedWorkspaces.length}</span>
            </div>
            <div className="-mr-1 min-h-0 overflow-y-auto pr-1">
              <NavList
                items={groupedWorkspaces}
                selectedKey={resolvedSelectedDomain}
                onSelect={setSelectedDomain}
                getKey={(ws) => ws.domain}
                renderLabel={(ws) => ws.domain}
                renderMeta={(ws) => {
                  const selectorCount = ws.surfaces.reduce((c, s) => c + s.selectorCount, 0);
                  const profileCount = ws.surfaces.filter((s) => s.profile).length;
                  const meta = [
                    selectorCount ? `${selectorCount} selectors` : null,
                    profileCount ? `${profileCount} profiles` : null,
                    ws.learning.length ? `${ws.learning.length} learned` : null,
                    ws.completedRunCount ? `${ws.completedRunCount} runs` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ');
                  return meta ? <span className="text-muted text-xs">{meta}</span> : null;
                }}
                renderBadge={(ws) =>
                  ws.cookieMemory ? (
                    <Badge tone="accent">{ws.cookieMemory.cookie_count}</Badge>
                  ) : null
                }
              />
            </div>
          </SurfacePanel>

          {/* ── Domain detail ── */}
          <div className="space-y-4">
            {selectedWorkspace ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-foreground type-heading text-lg font-semibold">
                    {selectedWorkspace.domain}
                  </h2>
                  {selectedWorkspace.surfaces.some((surface) => surface.selectorCount) ? (
                    <Button
                      type="button"
                      variant="danger"
                      size="sm"
                      onClick={() => void deleteDomainSelectors(selectedWorkspace.domain)}
                    >
                      <Trash2 className="size-3.5" />
                      Clear Selectors
                    </Button>
                  ) : null}
                </div>

                <TabBar
                  value={activeTab}
                  onChange={setActiveTab}
                  options={[
                    {
                      value: 'selectors',
                      label: `Selectors (${selectedWorkspace.surfaces.reduce((c, s) => c + s.selectorCount, 0)})`,
                    },
                    {
                      value: 'profiles',
                      label: `Profiles (${selectedWorkspace.surfaces.filter((s) => s.profile).length})`,
                    },
                    {
                      value: 'cookies',
                      label: `Cookies${selectedWorkspace.cookieMemory ? ` (${selectedWorkspace.cookieMemory.cookie_count})` : ''}`,
                    },
                    {
                      value: 'learning',
                      label: `Learning (${selectedWorkspace.learning.length})`,
                    },
                  ]}
                />

                {/* ── Selectors tab ── */}
                {activeTab === 'selectors' && (
                  <SurfaceSection
                    title="Selector Memory"
                    description="Review and edit the selectors currently saved for this domain."
                    bodyClassName="space-y-4"
                  >
                    {selectorLoading && loadedSelectorDomain !== selectedWorkspace.domain ? (
                      <DataRegionLoading count={6} className="px-0" />
                    ) : selectedWorkspace.surfaces.some((surface) => surface.selectorCount) ? (
                      selectedWorkspace.surfaces.map((surfaceWorkspace) => (
                        <div
                          key={`${selectedWorkspace.domain}:${surfaceWorkspace.surface}`}
                          className="border-subtle-panel-border bg-subtle-panel space-y-3 rounded-[var(--radius-xl)] border p-4"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <div className="text-foreground text-sm font-medium">
                                {surfaceLabel(surfaceWorkspace.surface)}
                              </div>
                              <div className="text-muted text-xs">
                                {surfaceWorkspace.selectorCount} selector
                                {surfaceWorkspace.selectorCount === 1 ? '' : 's'}
                              </div>
                            </div>
                            {surfaceWorkspace.profile ? (
                              <Badge tone="info">profile saved</Badge>
                            ) : null}
                          </div>

                          {surfaceWorkspace.selectors.length ? (
                            <div className="space-y-3">
                              {surfaceWorkspace.selectors.map((record) => {
                                const isEditing = editingId === record._uid && draft !== null;
                                return (
                                  <DetailRow
                                    key={record._uid}
                                    className={isEditing ? 'bg-subtle-panel' : undefined}
                                  >
                                    {isEditing ? (
                                      <div className="space-y-3">
                                        <div className="grid gap-3 md:grid-cols-2">
                                          <label className="grid gap-1.5">
                                            <span className="field-label">Field</span>
                                            <Input
                                              value={draft.field_name}
                                              onChange={(event) =>
                                                setDraft((current) =>
                                                  current
                                                    ? { ...current, field_name: event.target.value }
                                                    : current,
                                                )
                                              }
                                            />
                                          </label>
                                          <label className="grid gap-1.5">
                                            <span className="field-label">Source</span>
                                            <Input
                                              value={draft.source}
                                              onChange={(event) =>
                                                setDraft((current) =>
                                                  current
                                                    ? { ...current, source: event.target.value }
                                                    : current,
                                                )
                                              }
                                            />
                                          </label>
                                        </div>
                                        <label className="grid gap-1.5">
                                          <span className="field-label">Selector Kind</span>
                                          <select
                                            value={draft.kind}
                                            onChange={(event) =>
                                              setDraft((current) =>
                                                current
                                                  ? {
                                                      ...current,
                                                      kind: event.target.value as EditDraft['kind'],
                                                    }
                                                  : current,
                                              )
                                            }
                                            className="border-divider bg-background rounded-[var(--radius-md)] border px-3 py-2 text-sm"
                                          >
                                            <option value="css_selector">CSS Selector</option>
                                            <option value="xpath">XPath</option>
                                            <option value="regex">Regex</option>
                                          </select>
                                        </label>
                                        <label className="grid gap-1.5">
                                          <span className="field-label">Selector</span>
                                          <Input
                                            value={draft.selectorValue}
                                            onChange={(event) =>
                                              setDraft((current) =>
                                                current
                                                  ? {
                                                      ...current,
                                                      selectorValue: event.target.value,
                                                    }
                                                  : current,
                                              )
                                            }
                                          />
                                        </label>
                                        <label className="text-secondary flex items-center gap-2 text-sm">
                                          <input
                                            type="checkbox"
                                            checked={draft.is_active}
                                            onChange={(event) =>
                                              setDraft((current) =>
                                                current
                                                  ? { ...current, is_active: event.target.checked }
                                                  : current,
                                              )
                                            }
                                          />
                                          Active selector
                                        </label>
                                        <div className="flex flex-wrap gap-2">
                                          <Button
                                            type="button"
                                            variant="accent"
                                            onClick={() => void saveEdit(record)}
                                          >
                                            <Save className="size-3.5" />
                                            Save
                                          </Button>
                                          <Button
                                            type="button"
                                            variant="ghost"
                                            onClick={cancelEdit}
                                          >
                                            <X className="size-3.5" />
                                            Cancel
                                          </Button>
                                        </div>
                                      </div>
                                    ) : (
                                      <div className="flex flex-wrap items-start justify-between gap-3">
                                        <div className="min-w-0 flex-1">
                                          <div className="flex flex-wrap items-center gap-3">
                                            <span className="text-foreground font-medium">
                                              {record.field_name}
                                            </span>
                                            <Toggle
                                              checked={record.is_active}
                                              onChange={() => void toggleActive(record)}
                                              ariaLabel={
                                                record.is_active
                                                  ? 'Disable selector'
                                                  : 'Enable selector'
                                              }
                                            />
                                            <span className="text-muted text-xs">
                                              {titleCaseToken(record.source)}
                                            </span>
                                          </div>
                                          <code className="text-secondary mt-2 block text-xs break-all">
                                            {selectorValue(record)}
                                          </code>
                                          {record.sample_value ? (
                                            <div className="text-muted mt-2 text-xs">
                                              Sample: {record.sample_value}
                                            </div>
                                          ) : null}
                                        </div>
                                        <div className="flex items-center gap-1">
                                          <Button
                                            type="button"
                                            variant="ghost"
                                            size="icon"
                                            onClick={() => startEdit(record)}
                                            aria-label="Edit selector"
                                          >
                                            <Pencil className="size-3.5" />
                                          </Button>
                                          <Button
                                            type="button"
                                            variant="danger"
                                            size="icon"
                                            onClick={() => void deleteRecord(record)}
                                            aria-label="Delete selector"
                                          >
                                            <Trash2 className="size-3.5" />
                                          </Button>
                                        </div>
                                      </div>
                                    )}
                                  </DetailRow>
                                );
                              })}
                            </div>
                          ) : (
                            <MutedPanelMessage
                              title="No selectors"
                              description="No selectors saved for this surface yet."
                            />
                          )}
                        </div>
                      ))
                    ) : (
                      <DataRegionEmpty
                        title="No saved selector memory"
                        description="Selectors promoted from completed runs will appear here once they are saved."
                      />
                    )}
                  </SurfaceSection>
                )}

                {/* ── Profiles tab ── */}
                {activeTab === 'profiles' && (
                  <SurfaceSection
                    title="Run Profile Defaults"
                    description="Edit and save reusable fetch defaults here. Domain Memory is the canonical home for saved run profiles."
                    bodyClassName="space-y-3"
                  >
                    {selectedWorkspace.surfaces.some(
                      (surface) => surface.profile || surface.completedRuns.length,
                    ) ? (
                      selectedWorkspace.surfaces
                        .filter((surface) => surface.profile || surface.completedRuns.length)
                        .map((surface) => (
                          <DetailRow key={`${selectedWorkspace.domain}:${surface.surface}:profile`}>
                            {(() => {
                              const profile = profileDraftFor(selectedWorkspace.domain, surface);
                              const sourceRunId = latestCompletedRunId(surface);
                              const saveKey = profileDraftKey(
                                selectedWorkspace.domain,
                                surface.surface,
                              );
                              return (
                                <>
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div>
                                      <div className="text-foreground text-sm font-medium">
                                        {surfaceLabel(surface.surface)}
                                      </div>
                                      <div className="text-muted text-xs">
                                        Saved {formatTimestamp(surface.profile?.updated_at ?? null)}{' '}
                                        · Source run {sourceRunId ?? '—'}
                                      </div>
                                    </div>
                                    <Button
                                      type="button"
                                      variant="accent"
                                      size="sm"
                                      disabled={!sourceRunId || profileSaveKey === saveKey}
                                      onClick={() =>
                                        void saveProfile(selectedWorkspace.domain, surface)
                                      }
                                    >
                                      <Save className="size-3.5" />
                                      {profileSaveKey === saveKey ? 'Saving...' : 'Save Profile'}
                                    </Button>
                                  </div>
                                  <div className="mt-3 grid gap-3 md:grid-cols-3">
                                    <div className="grid content-start gap-3 md:col-span-2 md:grid-cols-2">
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Fetch Mode</span>
                                        <Dropdown
                                          value={profile.fetch_profile.fetch_mode}
                                          onChange={(value) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                fetch_profile: {
                                                  ...current.fetch_profile,
                                                  fetch_mode: value,
                                                },
                                              }),
                                            )
                                          }
                                          options={[
                                            { value: 'auto', label: 'Auto' },
                                            { value: 'http_only', label: 'HTTP Only' },
                                            { value: 'browser_only', label: 'Browser Only' },
                                            {
                                              value: 'http_then_browser',
                                              label: 'HTTP Then Browser',
                                            },
                                          ]}
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Extraction Source</span>
                                        <Dropdown
                                          value={profile.fetch_profile.extraction_source}
                                          onChange={(value) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                fetch_profile: {
                                                  ...current.fetch_profile,
                                                  extraction_source: value,
                                                },
                                              }),
                                            )
                                          }
                                          options={[
                                            { value: 'raw_html', label: 'Raw HTML' },
                                            { value: 'rendered_dom', label: 'Rendered DOM' },
                                            {
                                              value: 'rendered_dom_visual',
                                              label: 'Rendered DOM + Visual',
                                            },
                                            {
                                              value: 'network_payload_first',
                                              label: 'Network Payload First',
                                            },
                                          ]}
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">JS Mode</span>
                                        <Dropdown
                                          value={profile.fetch_profile.js_mode}
                                          onChange={(value) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                fetch_profile: {
                                                  ...current.fetch_profile,
                                                  js_mode: value,
                                                },
                                              }),
                                            )
                                          }
                                          options={[
                                            { value: 'auto', label: 'Auto' },
                                            { value: 'enabled', label: 'Enabled' },
                                            { value: 'disabled', label: 'Disabled' },
                                          ]}
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Traversal Mode</span>
                                        <Dropdown
                                          value={profile.fetch_profile.traversal_mode ?? ''}
                                          onChange={(value) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                fetch_profile: {
                                                  ...current.fetch_profile,
                                                  traversal_mode: value ? value : null,
                                                },
                                              }),
                                            )
                                          }
                                          options={[
                                            { value: '', label: 'Off' },
                                            { value: 'auto', label: 'Auto' },
                                            { value: 'scroll', label: 'Scroll' },
                                            { value: 'load_more', label: 'Load More' },
                                            { value: 'view_all', label: 'View All' },
                                            { value: 'paginate', label: 'Paginate' },
                                          ]}
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Geo Country</span>
                                        <Input
                                          value={profile.locality_profile.geo_country}
                                          onChange={(event) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                locality_profile: {
                                                  ...current.locality_profile,
                                                  geo_country: event.target.value || 'auto',
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Language Hint</span>
                                        <Input
                                          value={profile.locality_profile.language_hint ?? ''}
                                          onChange={(event) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                locality_profile: {
                                                  ...current.locality_profile,
                                                  language_hint: event.target.value || null,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Currency Hint</span>
                                        <Input
                                          value={profile.locality_profile.currency_hint ?? ''}
                                          onChange={(event) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                locality_profile: {
                                                  ...current.locality_profile,
                                                  currency_hint: event.target.value || null,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Network Capture</span>
                                        <Dropdown
                                          value={profile.diagnostics_profile.capture_network}
                                          onChange={(value) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                diagnostics_profile: {
                                                  ...current.diagnostics_profile,
                                                  capture_network: value,
                                                },
                                              }),
                                            )
                                          }
                                          options={[
                                            { value: 'off', label: 'Off' },
                                            { value: 'matched_only', label: 'Matched Only' },
                                            { value: 'all_small_json', label: 'All Small JSON' },
                                          ]}
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">
                                          Preferred Browser Engine
                                        </span>
                                        <Dropdown
                                          value={
                                            profile.acquisition_contract.preferred_browser_engine
                                          }
                                          onChange={(value) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                acquisition_contract: {
                                                  ...current.acquisition_contract,
                                                  preferred_browser_engine: value as
                                                    | 'auto'
                                                    | 'patchright'
                                                    | 'real_chrome',
                                                },
                                              }),
                                            )
                                          }
                                          options={[
                                            { value: 'auto', label: 'Auto' },
                                            { value: 'patchright', label: 'Patchright' },
                                            { value: 'real_chrome', label: 'Real Chrome' },
                                          ]}
                                        />
                                      </label>
                                      <label className="grid gap-1.5">
                                        <span className="field-label">Handoff Cookie Engine</span>
                                        <Dropdown
                                          value={profile.acquisition_contract.handoff_cookie_engine}
                                          onChange={(value) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                acquisition_contract: {
                                                  ...current.acquisition_contract,
                                                  handoff_cookie_engine: value as
                                                    | 'auto'
                                                    | 'patchright'
                                                    | 'real_chrome',
                                                },
                                              }),
                                            )
                                          }
                                          options={[
                                            { value: 'auto', label: 'Auto' },
                                            { value: 'patchright', label: 'Patchright' },
                                            { value: 'real_chrome', label: 'Real Chrome' },
                                          ]}
                                        />
                                      </label>
                                    </div>
                                    <div className="flex flex-col gap-3">
                                      <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                        <span className="text-sm font-medium">Prefer Browser</span>
                                        <Toggle
                                          checked={profile.acquisition_contract.prefer_browser}
                                          onChange={(checked) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                acquisition_contract: {
                                                  ...current.acquisition_contract,
                                                  prefer_browser: checked,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </div>
                                      <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                        <span className="text-sm font-medium">
                                          Prefer Curl Handoff
                                        </span>
                                        <Toggle
                                          checked={profile.acquisition_contract.prefer_curl_handoff}
                                          onChange={(checked) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                acquisition_contract: {
                                                  ...current.acquisition_contract,
                                                  prefer_curl_handoff: checked,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </div>
                                      <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                        <span className="text-sm font-medium">Include iframes</span>
                                        <Toggle
                                          checked={profile.fetch_profile.include_iframes}
                                          onChange={(checked) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                fetch_profile: {
                                                  ...current.fetch_profile,
                                                  include_iframes: checked,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </div>
                                      <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                        <span className="text-sm font-medium">Capture HTML</span>
                                        <Toggle
                                          checked={profile.diagnostics_profile.capture_html}
                                          onChange={(checked) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                diagnostics_profile: {
                                                  ...current.diagnostics_profile,
                                                  capture_html: checked,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </div>
                                      <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                        <span className="text-sm font-medium">
                                          Capture Screenshot
                                        </span>
                                        <Toggle
                                          checked={profile.diagnostics_profile.capture_screenshot}
                                          onChange={(checked) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                diagnostics_profile: {
                                                  ...current.diagnostics_profile,
                                                  capture_screenshot: checked,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </div>
                                      <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                        <span className="text-sm font-medium">
                                          Capture Response Headers
                                        </span>
                                        <Toggle
                                          checked={
                                            profile.diagnostics_profile.capture_response_headers
                                          }
                                          onChange={(checked) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                diagnostics_profile: {
                                                  ...current.diagnostics_profile,
                                                  capture_response_headers: checked,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </div>
                                      <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                        <span className="text-sm font-medium">
                                          Capture Browser Diagnostics
                                        </span>
                                        <Toggle
                                          checked={
                                            profile.diagnostics_profile.capture_browser_diagnostics
                                          }
                                          onChange={(checked) =>
                                            updateProfileDraft(
                                              selectedWorkspace.domain,
                                              surface,
                                              (current) => ({
                                                ...current,
                                                diagnostics_profile: {
                                                  ...current.diagnostics_profile,
                                                  capture_browser_diagnostics: checked,
                                                },
                                              }),
                                            )
                                          }
                                        />
                                      </div>
                                    </div>
                                  </div>
                                </>
                              );
                            })()}
                          </DetailRow>
                        ))
                    ) : (
                      <DataRegionEmpty
                        title="No saved run profiles"
                        description="Complete a crawl for this domain, then save reusable defaults here."
                      />
                    )}
                  </SurfaceSection>
                )}

                {/* ── Cookies tab ── */}
                {activeTab === 'cookies' && (
                  <SurfaceSection
                    title="Saved Domain Cookies"
                    description="Cookie memory is stored at the domain level so acquisition can reuse known session context."
                    bodyClassName="space-y-3"
                  >
                    {selectedWorkspace.cookieMemory ? (
                      <DetailRow>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <KVTile
                            label="Cookies"
                            value={selectedWorkspace.cookieMemory.cookie_count}
                          />
                          <KVTile
                            label="Origins"
                            value={selectedWorkspace.cookieMemory.origin_count}
                          />
                        </div>
                        <div className="text-muted mt-3 text-xs">
                          Updated {formatTimestamp(selectedWorkspace.cookieMemory.updated_at)}
                        </div>
                      </DetailRow>
                    ) : (
                      <DataRegionEmpty
                        title="No cookie memory saved"
                        description="A successful authenticated or protected acquisition run will populate cookie memory here."
                      />
                    )}
                  </SurfaceSection>
                )}

                {/* ── Learning tab ── */}
                {activeTab === 'learning' && (
                  <SurfaceSection
                    title="Recent Learning"
                    description="Latest keep and reject decisions captured for this domain across all surfaces."
                    bodyClassName="space-y-2"
                  >
                    {selectedWorkspace.learning.length ? (
                      selectedWorkspace.learning.slice(0, 8).map((row) => (
                        <DetailRow key={row.id}>
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone={row.action === 'reject' ? 'warning' : 'success'}>
                              {row.action}
                            </Badge>
                            <span className="text-foreground text-sm font-normal">
                              {row.field_name}
                            </span>
                            <Badge tone="neutral">{surfaceLabel(row.surface)}</Badge>
                          </div>
                          <div className="text-secondary mt-2 text-xs">
                            Source: {row.source_kind}
                            {row.source_value ? ` · Value: ${row.source_value}` : ''}
                          </div>
                          {row.selector_value ? (
                            <code className="text-muted mt-2 block text-xs break-all">
                              {row.selector_value}
                            </code>
                          ) : null}
                          <div className="text-muted mt-2 text-xs">
                            {formatTimestamp(row.created_at)}
                          </div>
                        </DetailRow>
                      ))
                    ) : (
                      <DataRegionEmpty
                        title="No recent learning"
                        description="Use the Learning tab on a completed run to keep or reject field evidence and populate this history."
                      />
                    )}
                  </SurfaceSection>
                )}
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
