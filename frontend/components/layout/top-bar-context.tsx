'use client';

import { createContext, useContext, useMemo, useRef, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';

export type TopBarState = {
  title?: ReactNode;
  description?: string;
  actions?: ReactNode;
};

type TopBarStore = {
  getSnapshot: () => TopBarState | null;
  subscribe: (listener: () => void) => () => void;
  setHeader: (value: TopBarState | null) => void;
};

const TopBarContext = createContext<TopBarStore | null>(null);

export function TopBarProvider({ children }: Readonly<{ children: ReactNode }>) {
  const headerRef = useRef<TopBarState | null>(null);
  const listenersRef = useRef(new Set<() => void>());

  const store = useMemo<TopBarStore>(
    () => ({
      getSnapshot: () => headerRef.current,
      subscribe: (listener) => {
        listenersRef.current.add(listener);
        return () => {
          listenersRef.current.delete(listener);
        };
      },
      setHeader: (value) => {
        headerRef.current = value;
        for (const listener of listenersRef.current) {
          listener();
        }
      },
    }),
    [],
  );

  return <TopBarContext.Provider value={store}>{children}</TopBarContext.Provider>;
}

export function useTopBarStore() {
  const context = useContext(TopBarContext);
  if (!context) {
    throw new Error('useTopBarStore must be used within TopBarProvider');
  }
  return context;
}

export function useTopBarHeader() {
  const store = useTopBarStore();
  return useSyncExternalStore(store.subscribe, store.getSnapshot, () => null);
}
