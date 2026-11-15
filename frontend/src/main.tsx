import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { App } from "./app/App";
import { retryDelay, shouldRetry } from "./lib/queryPolicy";
import "./index.css";

const queryClient = new QueryClient({
  // Transient failures (no answer, 502 while the server restarts) back off with jitter;
  // game rules (4xx) are never retried. Mutations are never retried automatically.
  defaultOptions: { queries: { retry: shouldRetry, retryDelay, refetchOnWindowFocus: false }, mutations: { retry: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary><App /></ErrorBoundary>
    </QueryClientProvider>
  </StrictMode>,
);
