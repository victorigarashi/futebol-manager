import { describe, expect, it } from "vitest";

import { assertCanPrepare, createPESRuntimeBridge, RuntimeUnavailableError } from "./bridge";
import { NO_CAPABILITIES, parseHostMessage, validateRuntimeOrigin } from "./protocol";

const APP = "http://127.0.0.1:5174";
const HOST = "http://127.0.0.1:8765";
const SUM = "sha256:" + "a".repeat(64);

describe("PES runtime bridge (no runtime validated)", () => {
  it("refuses every operation and exposes no capability", async () => {
    const bridge = createPESRuntimeBridge();
    expect(bridge.state).toBe("UNAVAILABLE");
    expect(Object.values(bridge.capabilities).every((v) => v === false)).toBe(true);
    await expect(bridge.connect(null as unknown as HTMLElement, HOST)).rejects.toBeInstanceOf(RuntimeUnavailableError);
    await expect(bridge.prepareMatch({ match_id: "m", checksum: SUM, payload: {} })).rejects.toThrow(/não validada/);
  });

  it("will not prepare a match until roster, team selection and the mode are validated", () => {
    expect(() => assertCanPrepare(NO_CAPABILITIES, "ELEVEN_A_SIDE")).toThrow(/elenco.*mandante.*11×11/);
    expect(() => assertCanPrepare({ ...NO_CAPABILITIES, can_load_custom_roster: true, can_select_teams: true, supports_11v11: true }, "FIVE_A_SIDE")).toThrow(/5×5/);
    expect(() => assertCanPrepare({ ...NO_CAPABILITIES, can_load_custom_roster: true, can_select_teams: true, supports_11v11: true }, "ELEVEN_A_SIDE")).not.toThrow();
  });
});

describe("runtime origin (isolation)", () => {
  it("accepts only the user's own machine, on another origin, with a port", () => {
    expect(validateRuntimeOrigin("http://127.0.0.1:8765/pes/index.html", APP)).toBe(HOST);
    expect(validateRuntimeOrigin("http://localhost:9000", APP)).toBe("http://localhost:9000");
    expect(() => validateRuntimeOrigin("https://pes-web.example.com:443", APP)).toThrow(/própria máquina/);
    expect(() => validateRuntimeOrigin("http://127.0.0.1", APP)).toThrow(/porta/);
    expect(() => validateRuntimeOrigin("http://127.0.0.1:5174/", APP)).toThrow(/origem diferente/);
    expect(() => validateRuntimeOrigin("file:///home/x/pes/index.html", APP)).toThrow(/http/);
    expect(() => validateRuntimeOrigin("http://user:pw@127.0.0.1:8765", APP)).toThrow(/credenciais/);
    expect(() => validateRuntimeOrigin("not a url", APP)).toThrow(/inválido/);
  });
});

describe("host page messages", () => {
  it("drops messages from another origin, another version or an unknown shape", () => {
    expect(parseHostMessage({ v: 1, type: "status", state: "MENU" }, "http://evil.test:80", HOST)).toBeNull();
    expect(parseHostMessage({ v: 2, type: "status", state: "MENU" }, HOST, HOST)).toBeNull();
    expect(parseHostMessage({ v: 1, type: "status", state: "WON" }, HOST, HOST)).toBeNull();
    expect(parseHostMessage({ v: 1, type: "unknown" }, HOST, HOST)).toBeNull();
    expect(parseHostMessage("ready", HOST, HOST)).toBeNull();
  });

  it("validates results strictly (checksum of the contract, integer goals)", () => {
    const ok = { v: 1, type: "result", match_id: "r8-1", payload_checksum: SUM, home_goals: 2, away_goals: 1 };
    expect(parseHostMessage(ok, HOST, HOST)).toEqual(ok);
    expect(parseHostMessage({ ...ok, home_goals: 2.5 }, HOST, HOST)).toBeNull();
    expect(parseHostMessage({ ...ok, away_goals: -1 }, HOST, HOST)).toBeNull();
    expect(parseHostMessage({ ...ok, payload_checksum: "sha256:xyz" }, HOST, HOST)).toBeNull();
    expect(parseHostMessage({ v: 1, type: "ready", runtime: { name: "PES 2013 Web", build: "worker-DBuE8yY4" } }, HOST, HOST)?.type).toBe("ready");
  });
});
