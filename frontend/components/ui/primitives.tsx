'use client';

import * as React from 'react';
import { useId } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

export { Badge, badgeVariants } from './badge';
export { Button, buttonVariants } from './button';
export { Card, cardVariants } from './card';
export { Input, Textarea, inputVariants, textareaVariants } from './input';
export { Metric, StatCard } from './metric';
export { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './table';

function sanitizeIdSegment(value: string) {
  const normalized = String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-');
  return normalized.replace(/^-+|-+$/g, '') || 'option';
}

/* ─── Title / Subtitle ───────────────────────────────────────────────────── */
export function Title({
  children,
  kicker,
  className,
}: Readonly<{ children: ReactNode; kicker?: string; className?: string }>) {
  return (
    <div className={cn('space-y-1', className)}>
      {kicker ? <p className="text-accent m-0 mb-1.5 text-sm font-medium">{kicker}</p> : null}
      <h1 className="text-foreground type-heading m-0 text-[clamp(1.75rem,1.45rem+0.8vw,2rem)] leading-[var(--leading-tight)] font-semibold">
        {children}
      </h1>
    </div>
  );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <p className="text-secondary mt-1.5 max-w-2xl text-sm leading-[var(--leading-relaxed)]">
      {children}
    </p>
  );
}

/* ─── Field ──────────────────────────────────────────────────────────────── */
export function Field({
  label,
  hint,
  children,
}: Readonly<{ label: string; hint?: string; children: ReactNode }>) {
  return (
    <label className="grid gap-1.5">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

/* ─── Dropdown (Clerk-style custom select) ───────────────────────────────── */
export function Dropdown<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  className,
  disabled = false,
  align = 'left',
}: Readonly<{
  value: T;
  onChange: (value: T) => void;
  options: Array<{ value: T; label: string }>;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
  align?: 'left' | 'center';
}>) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const listboxRef = React.useRef<HTMLDivElement>(null);
  const [listboxPosition, setListboxPosition] = React.useState<{
    top: number;
    left: number;
    width: number;
    side: 'top' | 'bottom';
  }>({ top: 0, left: 0, width: 0, side: 'bottom' });
  const closeTimerRef = React.useRef<number | undefined>(undefined);
  const dropdownId = useId().replace(/[^a-zA-Z0-9_-]+/g, '') || 'dropdown';
  const activeIndex = options.findIndex((o) => o.value === value);
  const listboxId = `${dropdownId}-listbox`;
  const activeDescendant =
    activeIndex >= 0
      ? `${dropdownId}-option-${activeIndex}-${sanitizeIdSegment(options[activeIndex].value)}`
      : undefined;

  if (process.env.NODE_ENV === 'development' && activeIndex === -1 && options.length > 0) {
    console.warn(`Dropdown: value "${value}" not found in options`);
  }

  function scheduleClose() {
    closeTimerRef.current = window.setTimeout(() => setOpen(false), 120) as unknown as number;
  }

  function cancelClose() {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = undefined;
    }
  }

  const updatePosition = React.useCallback(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const menuHeight = listboxRef.current?.offsetHeight ?? options.length * 36 + 8; // Estimate if not measured
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const shouldFlip = spaceBelow < menuHeight && rect.top > menuHeight;

    setListboxPosition({
      top: shouldFlip ? rect.top - menuHeight - 4 : rect.bottom + 4,
      left: rect.left,
      width: rect.width,
      side: shouldFlip ? 'top' : 'bottom',
    });
  }, [options.length]);

  React.useLayoutEffect(() => {
    if (open) {
      updatePosition();
      const handleResize = () => updatePosition();
      const handleScroll = () => updatePosition();
      window.addEventListener('resize', handleResize);
      window.addEventListener('scroll', handleScroll, true);
      return () => {
        window.removeEventListener('resize', handleResize);
        window.removeEventListener('scroll', handleScroll, true);
      };
    }
  }, [open, updatePosition]);

  React.useEffect(() => {
    return () => {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    };
  }, []);

  React.useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node) &&
        listboxRef.current &&
        !listboxRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open && (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown')) {
      e.preventDefault();
      setOpen(true);
      return;
    }
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = (activeIndex + 1) % options.length;
      onChange(options[next].value);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = (activeIndex - 1 + options.length) % options.length;
      onChange(options[prev].value);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setOpen(false);
    }
  }

  const selectedLabel = options[activeIndex]?.label ?? value;

  return (
    <div
      ref={containerRef}
      className={cn('relative', className)}
      onMouseEnter={() => {
        if (!disabled) {
          cancelClose();
          setOpen(true);
        }
      }}
      onMouseLeave={() => {
        if (open) scheduleClose();
      }}
    >
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-activedescendant={activeDescendant}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        onKeyDown={handleKeyDown}
        className={cn(
          'focus-ring border-border-strong bg-background-elevated text-foreground hover:bg-background-alt focus:border-accent flex h-[var(--control-height)] w-full items-center gap-2 rounded-[var(--radius-md)] border px-3 text-sm leading-[1.4] font-medium shadow-sm transition-[background-color,border-color,box-shadow] focus:shadow-[0_0_0_3px_var(--accent-subtle)]',
          align === 'center' ? 'justify-center text-center' : 'justify-between text-left',
        )}
      >
        <span className="truncate">{selectedLabel}</span>
        <svg
          className={cn(
            'text-muted size-3.5 shrink-0 transition-transform duration-150',
            open && 'rotate-180',
            align === 'center' ? 'absolute right-3' : 'relative',
          )}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>
      {open && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={listboxRef}
              id={listboxId}
              role="listbox"
              onMouseEnter={cancelClose}
              onMouseLeave={scheduleClose}
              className={cn(
                'border-border bg-background-elevated fixed z-[300] w-max rounded-[var(--radius-lg)] border py-1 shadow-lg overflow-y-auto max-h-[320px]',
                listboxPosition.side === 'bottom'
                  ? 'animate-[dropdown-in_150ms_cubic-bezier(0.16,1,0.3,1)]'
                  : 'animate-[dropdown-in-up_150ms_cubic-bezier(0.16,1,0.3,1)]',
              )}
              style={{
                top: `${listboxPosition.top}px`,
                left: `${listboxPosition.left}px`,
                minWidth: `${listboxPosition.width}px`,
              }}
            >
              {options.map((option, index) => {
                const optionId = `${dropdownId}-option-${index}-${sanitizeIdSegment(option.value)}`;
                return (
                  <button
                    key={option.value}
                    id={optionId}
                    role="option"
                    aria-selected={option.value === value}
                    onClick={() => {
                      onChange(option.value);
                      setOpen(false);
                    }}
                    onMouseDown={(e) => e.preventDefault()}
                    className={cn(
                      'flex w-full items-center py-2 text-sm leading-[var(--leading-snug)] transition-colors',
                      align === 'center' ? 'justify-center px-8' : 'justify-start px-3',
                      option.value === value
                        ? 'bg-accent-subtle text-accent font-medium'
                        : 'text-foreground hover:bg-background-alt',
                    )}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

/* ─── Toggle ─────────────────────────────────────────────────────────────── */
export function Toggle({
  checked,
  onChange,
  ariaLabel,
}: Readonly<{ checked: boolean; onChange: (v: boolean) => void; ariaLabel?: string }>) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={ariaLabel}
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'focus-ring relative inline-flex h-[20px] w-[36px] shrink-0 cursor-pointer items-center rounded-full transition-colors',
        checked ? 'bg-accent' : 'bg-border-strong',
      )}
    >
      <span
        className={cn(
          'inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform',
          checked ? 'translate-x-[16px]' : 'translate-x-[2px]',
        )}
      />
    </button>
  );
}

/* ─── Skeleton ───────────────────────────────────────────────────────────── */
export function Skeleton({ className }: Readonly<{ className?: string }>) {
  return <div className={cn('skeleton', className)} aria-hidden="true" />;
}

/* ─── Tooltip ────────────────────────────────────────────────────────────── */
export function Tooltip({
  children,
  content,
  className,
  align = 'center',
}: Readonly<{
  children: ReactNode;
  content: string;
  className?: string;
  align?: 'center' | 'start';
}>) {
  const tooltipId = useId();
  const child = React.Children.only(children);
  const anchorRef = React.useRef<HTMLDivElement>(null);
  const tooltipRef = React.useRef<HTMLDivElement>(null);
  const [open, setOpen] = React.useState(false);
  const [position, setPosition] = React.useState<{ left: number; top: number }>({
    left: 0,
    top: 0,
  });
  const enhancedChild = React.isValidElement(child)
    ? React.cloneElement(child, {
        'aria-describedby': tooltipId,
      } as React.HTMLAttributes<HTMLElement>)
    : child;

  const updatePosition = React.useCallback(() => {
    if (!anchorRef.current || !tooltipRef.current) {
      return;
    }
    const anchorRect = anchorRef.current.getBoundingClientRect();
    const tooltipRect = tooltipRef.current.getBoundingClientRect();
    const margin = 12;
    const idealLeft =
      align === 'start'
        ? anchorRect.left
        : anchorRect.left + anchorRect.width / 2 - tooltipRect.width / 2;
    const maxLeft = window.innerWidth - tooltipRect.width - margin;
    const nextLeft = Math.min(Math.max(idealLeft, margin), Math.max(margin, maxLeft));
    const nextTop = Math.max(margin, anchorRect.top - tooltipRect.height - 8);
    setPosition({ left: nextLeft, top: nextTop });
  }, [align, setPosition]);

  React.useLayoutEffect(() => {
    if (!open) {
      return;
    }
    updatePosition();
  }, [open, content, updatePosition]);

  React.useEffect(() => {
    if (!open) {
      return;
    }
    const handleLayout = () => updatePosition();
    window.addEventListener('resize', handleLayout);
    window.addEventListener('scroll', handleLayout, true);
    return () => {
      window.removeEventListener('resize', handleLayout);
      window.removeEventListener('scroll', handleLayout, true);
    };
  }, [open, updatePosition]);

  return (
    <div
      ref={anchorRef}
      className={cn('relative flex items-center', className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      {enhancedChild}
      {open && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={tooltipRef}
              id={tooltipId}
              role="tooltip"
              className={cn(
                'pointer-events-none fixed w-max max-w-[min(420px,calc(100vw-24px))]',
                'tooltip-surface bg-panel rounded-[var(--radius-md)] px-2 py-1.5 shadow-lg',
                'text-foreground z-[200] text-sm leading-normal font-medium break-words',
              )}
              style={{ left: `${position.left}px`, top: `${position.top}px` }}
            >
              {content}
              <div
                className="border-border-strong bg-panel absolute -bottom-[6px] size-2.5 border-r border-b"
                style={{
                  left: align === 'start' ? '12px' : '50%',
                  transform: align === 'start' ? 'rotate(45deg)' : 'translateX(-50%) rotate(45deg)',
                }}
              />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
