import { afterEach, describe, expect, it } from "vitest";

import { backoffDelay, reportServerHealth, resetServerHealth, serverHealth, subscribeServerHealth } from "./serverHealth";

afterEach(() => resetServerHealth());

describe("server health", () => {
  it("treats one failure as noise and repeated 502s as an outage", () => {
    reportServerHealth("unavailable");
    expect(serverHealth()).toBe("degraded");
    reportServerHealth("unavailable");
    expect(serverHealth()).toBe("unavailable");
  });

  it("distinguishes a network loss from a server restart", () => {
    reportServerHealth("network");
    reportServerHealth("network");
    expect(serverHealth()).toBe("offline");
  });

  it("recovers on the first successful answer and notifies subscribers", () => {
    const seen: string[] = [];
    subscribeServerHealth((health) => seen.push(health));
    reportServerHealth("unavailable");
    reportServerHealth("unavailable");
    reportServerHealth("ok");
    expect(serverHealth()).toBe("ok");
    expect(seen).toEqual(["degraded", "unavailable", "ok"]);
  });
});

describe("backoff", () => {
  it("grows exponentially, stays within [ceiling/2, ceiling] and is capped", () => {
    expect(backoffDelay(0, 500, 15_000, () => 0)).toBe(250);
    expect(backoffDelay(0, 500, 15_000, () => 1)).toBe(500);
    expect(backoffDelay(3, 500, 15_000, () => 1)).toBe(4000);
    expect(backoffDelay(10, 500, 15_000, () => 1)).toBe(15_000);
    expect(backoffDelay(10, 500, 15_000, () => 0)).toBe(7500);
  });
});
