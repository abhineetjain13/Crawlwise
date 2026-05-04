'use client';

import { History, X } from 'lucide-react';
import React, { useEffect } from 'react';

import { Badge, Button } from './primitives';
import { cn } from '../../lib/utils';

export type HistoryItem = {
  id: number;
  status: string;
  created_at: string;
  label?: string;
  meta?: string;
};

const STATUS_TONE_MAP: Record<string, 'success' | 'danger' | 'neutral' | 'warning' | 'info'> = {
  complete: 'success',
  completed: 'success',
  success: 'success',
  failed: 'danger',
  error: 'danger',
  running: 'info',
  pending: 'neutral',
};

export function HistoryDrawer({
  open,
  onClose,
  items,
  activeId,
  onSelect,
  title = 'Run History',
}: Readonly<{
  open: boolean;
  onClose: () => void;
  items: HistoryItem[];
  activeId?: number | null;
  onSelect: (id: number) => void;
  title?: string;
}>) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div className="border-divider bg-background-elevated animate-in slide-in-from-right-4 fixed top-0 right-0 z-50 flex h-full w-[380px] max-w-full flex-col overflow-y-auto border-l p-0 shadow-xl duration-200">
        <div className="border-divider flex items-center justify-between border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <History className="text-muted size-4" />
            <h2 className="text-foreground type-heading text-sm font-medium">{title}</h2>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onClose}
            aria-label="Close history"
          >
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="flex-1 overflow-auto">
          {items.length === 0 ? (
            <div className="text-muted flex h-full flex-col items-center justify-center p-8 text-center">
              <History className="mb-3 size-8 opacity-20" />
              <p className="text-xs">No history found.</p>
            </div>
          ) : (
            <div className="divide-divider divide-y">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    'hover:bg-background-alt flex w-full flex-col gap-1.5 p-3.5 text-left transition-colors',
                    activeId === item.id && 'bg-background-alt',
                  )}
                  onClick={() => {
                    onSelect(item.id);
                    onClose();
                  }}
                >
                  <div className="flex w-full items-center justify-between">
                    <span
                      className={cn(
                        'text-accent type-label-mono font-medium',
                        activeId === item.id && 'font-bold',
                      )}
                    >
                      #{item.id}
                    </span>
                    <Badge
                      tone={STATUS_TONE_MAP[item.status] ?? 'neutral'}
                      className="origin-right scale-90"
                    >
                      {item.status}
                    </Badge>
                  </div>
                  {item.label && (
                    <div className="text-foreground type-body max-w-[300px] truncate font-semibold">
                      {item.label}
                    </div>
                  )}
                  <div className="text-muted type-caption flex w-full items-center justify-between">
                    <span>{item.meta ?? 'No details'}</span>
                    <span className="type-caption-mono">{formatShortDate(item.created_at)}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function formatShortDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
