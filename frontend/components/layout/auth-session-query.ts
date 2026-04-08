import { api } from "../../lib/api";

export const AUTH_SESSION_QUERY_KEY = ["me"] as const;

export function isAuthRoute(pathname: string | null) {
  return pathname === "/login" || pathname === "/register";
}

export function getAuthSessionQueryOptions(pathname: string | null) {
  return {
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: api.me,
    enabled: !isAuthRoute(pathname),
    retry: false,
    refetchOnWindowFocus: false,
  } as const;
}
