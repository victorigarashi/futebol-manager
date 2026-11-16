/**
 * The room WebSocket as seen by the rest of the app: whether it is online, and a way
 * to send small messages (client rendering stats) without owning the socket.
 */
type Sender = (text: string) => boolean;
let online = false;
let sender: Sender | null = null;
const listeners = new Set<(online: boolean) => void>();

export function setSocketOnline(value: boolean, send: Sender | null): void {
  sender = value ? send : null;
  if (online === value) return;
  online = value;
  for (const listener of listeners) listener(online);
}

export function socketOnline(): boolean { return online; }

export function subscribeSocket(listener: (online: boolean) => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function sendOverSocket(message: Record<string, unknown>): boolean {
  return sender ? sender(JSON.stringify(message)) : false;
}
