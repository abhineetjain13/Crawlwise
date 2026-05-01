'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';
import { Button } from './primitives';

type ConfirmDialogProps = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  pending?: boolean;
  danger?: boolean;
  error?: string;
  onConfirm: () => void;
}>;

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = 'Cancel',
  pending = false,
  danger = false,
  error,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(nextOpen) => !pending && onOpenChange(nextOpen)}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[100] bg-black/35 backdrop-blur-[2px]" />
        <DialogPrimitive.Content
          className={cn(
            'fixed top-1/2 left-1/2 z-[101] w-[min(420px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2',
            'border-border bg-panel rounded-[var(--radius-xl)] border p-5 shadow-xl',
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-foreground m-0 text-base leading-snug font-semibold">
                {title}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description className="text-secondary mt-2 text-sm leading-[var(--leading-relaxed)]">
                {description}
              </DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Close"
                disabled={pending}
              >
                <X className="size-4" />
              </Button>
            </DialogPrimitive.Close>
          </div>
          {error ? (
            <div
              role="alert"
              className="border-danger/20 bg-danger/10 text-danger mt-4 rounded-[var(--radius-md)] border px-3 py-2 text-sm leading-[var(--leading-normal)]"
            >
              {error}
            </div>
          ) : null}
          <div className="mt-5 flex justify-end gap-2">
            <DialogPrimitive.Close asChild>
              <Button type="button" variant="ghost" disabled={pending}>
                {cancelLabel}
              </Button>
            </DialogPrimitive.Close>
            <Button
              type="button"
              variant={danger ? 'danger' : 'primary'}
              disabled={pending}
              onClick={onConfirm}
            >
              {pending ? 'Working...' : confirmLabel}
            </Button>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
