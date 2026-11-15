import { ApiError } from "./api";
import { backoffDelay } from "./serverHealth";

/** Retry only what can succeed later (no answer, 5xx, 408/429) - never a game rule (4xx). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError) return error.transient && failureCount < 4;
  return failureCount < 2;
}

export function retryDelay(attempt: number): number {
  return backoffDelay(attempt, 600, 10_000);
}
