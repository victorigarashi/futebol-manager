import type { FormationSlot, InstructionOptions } from "../../lib/api";

export type InstructionRole = keyof InstructionOptions;

/** Same rule as the server (app.domain.cohesion.slot_role): wide defenders of a back four or five are full-backs. */
export function slotRole(slot: FormationSlot, slots: FormationSlot[]): InstructionRole {
  if (slot.position === "DF") {
    const line = slots.filter((other) => other.y === slot.y).length;
    return line >= 4 && (slot.x <= 25 || slot.x >= 75) ? "FB" : "CB";
  }
  return slot.position as InstructionRole;
}
