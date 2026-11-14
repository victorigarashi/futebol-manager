import { describe, expect, it } from "vitest";

import { roomSocketUrl } from "./api";

describe("roomSocketUrl", () => {
  it("converte a base HTTP no canal da sala", () => {
    const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
    const expected = base.replace(/^http/, "ws").replace(/\/api\/v1$/, "/api/v1/ws/rooms/sala-123");
    expect(roomSocketUrl("sala-123")).toBe(expected);
  });
});
