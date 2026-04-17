import { QueryClient } from "@tanstack/react-query";

// Use same-origin relative paths so the dashboard works from any LAN machine.
// nginx proxies /api/* → http://127.0.0.1:8000 on the server.
// Override with VITE_API_URL only for local dev (e.g. VITE_API_URL=http://192.168.4.31:8000).
const API_BASE = (import.meta.env.VITE_API_URL || "");

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 10_000,
      retry: 1,
    },
  },
});

export async function apiRequest(
  method: string,
  path: string,
  body?: unknown,
): Promise<Response> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${method} ${path} → ${res.status}: ${text}`);
  }
  return res;
}

export async function fetchJSON<T>(path: string): Promise<T> {
  const res = await apiRequest("GET", path);
  return res.json();
}
