import { afterEach, describe, expect, it, vi } from "vitest";
import { readLocal, removeLocal, writeLocal } from "./storage";
afterEach(() => vi.unstubAllGlobals());
describe("optional browser persistence", () => {
  it("survives blocked storage without interrupting the server session", () => {
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("quota"); }, removeItem: () => { throw new Error("blocked"); } });
    expect(readLocal("room")).toBeNull();
    expect(() => writeLocal("room", "id")).not.toThrow();
    expect(() => removeLocal("room")).not.toThrow();
  });
});
