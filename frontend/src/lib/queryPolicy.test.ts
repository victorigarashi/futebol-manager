import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { retryDelay, shouldRetry } from "./queryPolicy";

describe("query retry policy", () => {
  it("retries 502/503/504 and network failures a few times", () => {
    expect(shouldRetry(0, new ApiError("x", 502))).toBe(true);
    expect(shouldRetry(3, new ApiError("x", 503))).toBe(true);
    expect(shouldRetry(4, new ApiError("x", 504))).toBe(false);
    expect(shouldRetry(1, new ApiError("x", 0))).toBe(true);
  });

  it("never retries a rule the game enforced", () => {
    for (const status of [400, 401, 403, 404, 409, 422]) expect(shouldRetry(0, new ApiError("x", status))).toBe(false);
  });

  it("waits longer after each failure, with a cap", () => {
    expect(retryDelay(8)).toBeLessThanOrEqual(10_000);
    expect(retryDelay(0)).toBeLessThanOrEqual(600);
  });
});
