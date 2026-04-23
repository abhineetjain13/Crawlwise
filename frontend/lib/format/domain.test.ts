import { describe, expect, it } from "vitest";

import { isSpecialUseDomain } from "./domain";

describe("isSpecialUseDomain", () => {
 it("keeps bracketed IPv6 literals intact when stripping ports", () => {
 expect(isSpecialUseDomain("http://[::1]:3000")).toBe(false);
 });

 it("still detects localhost hosts with explicit ports", () => {
 expect(isSpecialUseDomain("localhost:3000")).toBe(true);
 expect(isSpecialUseDomain("http://localhost.localdomain:8080")).toBe(true);
 });
});
