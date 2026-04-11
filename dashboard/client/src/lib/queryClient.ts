import { QueryClient } from "@tanstack/react-query";

// Point to the Python agent API
const API_BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000");

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
