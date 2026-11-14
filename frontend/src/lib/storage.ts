// A blocked/full localStorage must never break a cookie-backed game session.
export function readLocal(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
export function writeLocal(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* Server membership remains authoritative. */ }
}
export function removeLocal(key: string): void {
  try { localStorage.removeItem(key); } catch { /* Optional convenience storage. */ }
}
