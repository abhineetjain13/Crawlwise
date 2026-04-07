"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

/**
* Provides a React Query client context to descendant components.
* @example
* QueryProvider({ children })
* <QueryClientProvider client={client}>...</QueryClientProvider>
* @param {{ children: React.ReactNode }} children - The React nodes to be rendered within the QueryClientProvider.
* @returns {JSX.Element} A QueryClientProvider wrapping the provided children.
**/
export function QueryProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            staleTime: 5_000,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
