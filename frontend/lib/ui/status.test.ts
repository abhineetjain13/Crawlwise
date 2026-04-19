import { describe, expect, it } from "vitest";

import { runExecutionLabel, runExecutionTone } from "./status";

describe("runExecutionStatus", () => {
  it("downgrades completed zero-result runs to warning", () => {
    expect(
      runExecutionTone("completed", {
        extraction_verdict: "listing_detection_failed",
        record_count: 0,
      }),
    ).toBe("warning");
    expect(
      runExecutionLabel("completed", {
        extraction_verdict: "listing_detection_failed",
        record_count: 0,
      }),
    ).toBe("Listing Failed");
  });

  it("marks completed blocked or error runs as danger", () => {
    expect(
      runExecutionTone("completed", {
        extraction_verdict: "error",
        record_count: 0,
      }),
    ).toBe("danger");
    expect(
      runExecutionLabel("completed", {
        extraction_verdict: "blocked",
        record_count: 0,
      }),
    ).toBe("Blocked");
  });
});
