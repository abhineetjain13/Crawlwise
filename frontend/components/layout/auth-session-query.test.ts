import { describe, expect, it } from"vitest";

import { api } from"../../lib/api";
import { AUTH_SESSION_QUERY_KEY, getAuthSessionQueryOptions, isAuthRoute } from"./auth-session-query";

describe("auth session query contract", () => {
 it("treats login and register as auth routes", () => {
 expect(isAuthRoute("/login")).toBe(true);
 expect(isAuthRoute("/register")).toBe(true);
 expect(isAuthRoute("/dashboard")).toBe(false);
 expect(isAuthRoute(null)).toBe(false);
 });

 it("uses a single, stable session query contract", () => {
 const options = getAuthSessionQueryOptions("/dashboard");

 expect(options.queryKey).toEqual(AUTH_SESSION_QUERY_KEY);
 expect(options.queryFn).toBe(api.me);
 expect(options.enabled).toBe(true);
 expect(options.retry).toBe(false);
 expect(options.refetchOnWindowFocus).toBe(false);
 });

 it("disables auth session query on auth routes", () => {
 expect(getAuthSessionQueryOptions("/login").enabled).toBe(false);
 expect(getAuthSessionQueryOptions("/register").enabled).toBe(false);
 });
});
