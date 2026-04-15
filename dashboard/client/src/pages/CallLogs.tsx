import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { Phone, PhoneOff, Search } from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import type { CallLog } from "@shared/schema";
import DispositionBadge from "@/components/DispositionBadge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

function formatDuration(s: number | null) {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function formatTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function CallLogs() {
  const [search, setSearch] = useState("");

  const { data: calls, isLoading } = useQuery<CallLog[]>({
    queryKey: ["/api/calls"],
    queryFn: () => fetchJSON("/api/calls?limit=200"),
    refetchInterval: 20_000,
  });

  const filtered = (calls || []).filter((c) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      c.caller_id?.toLowerCase().includes(q) ||
      c.intent?.toLowerCase().includes(q) ||
      c.intent_detail?.toLowerCase().includes(q) ||
      c.disposition?.toLowerCase().includes(q) ||
      c.transferred_to?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Call Logs</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {calls ? `${calls.length} calls total` : "Loading..."}
          </p>
        </div>
      </div>

      {/* Search */}
      <div className="relative max-w-xs">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          data-testid="input-search"
          placeholder="Search caller, intent..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-8 h-8 text-sm bg-secondary border-border"
        />
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-4 space-y-3">
            {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : !filtered.length ? (
          <div className="py-16 text-center text-muted-foreground text-sm">
            <PhoneOff size={36} className="mx-auto mb-3 opacity-25" />
            {search ? "No calls match your search" : "No calls recorded yet"}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border bg-muted/40">
                <th className="px-5 py-3 text-left font-medium">Caller ID</th>
                <th className="px-3 py-3 text-left font-medium">Started</th>
                <th className="px-3 py-3 text-left font-medium">Duration</th>
                <th className="px-3 py-3 text-left font-medium">Intent</th>
                <th className="px-3 py-3 text-left font-medium">Detail</th>
                <th className="px-3 py-3 text-left font-medium">Disposition</th>
                <th className="px-3 py-3 text-left font-medium">Ext</th>
                <th className="px-3 py-3" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((call) => (
                <tr key={call.id} className="call-row border-b border-border last:border-0">
                  <td className="px-5 py-3 font-mono text-xs text-foreground">{call.caller_id}</td>
                  <td className="px-3 py-3 text-muted-foreground text-xs whitespace-nowrap">{formatTime(call.started_at)}</td>
                  <td className="px-3 py-3 text-muted-foreground text-xs mono">{formatDuration(call.duration_seconds)}</td>
                  <td className="px-3 py-3 text-xs capitalize text-foreground/80">{call.intent || <span className="text-muted-foreground/40">—</span>}</td>
                  <td className="px-3 py-3 text-xs text-muted-foreground capitalize">{call.intent_detail || "—"}</td>
                  <td className="px-3 py-3">
                    <DispositionBadge disposition={call.disposition} />
                  </td>
                  <td className="px-3 py-3 text-xs mono text-muted-foreground">{call.transferred_to || "—"}</td>
                  <td className="px-3 py-3 text-right">
                    <Link href={`/calls/${call.call_id}`}>
                      <a className="text-xs text-primary hover:underline whitespace-nowrap">Transcript →</a>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
