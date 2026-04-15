import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { Phone, ArrowRight, CalendarClock, ArrowLeftRight, PhoneOff, Clock } from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import type { CallStats, CallLog } from "@shared/schema";
import DispositionBadge from "@/components/DispositionBadge";
import { Skeleton } from "@/components/ui/skeleton";

function formatDuration(s: number | null) {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function formatTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function Dashboard() {
  const { data: stats, isLoading: statsLoading } = useQuery<CallStats>({
    queryKey: ["/api/stats"],
    queryFn: () => fetchJSON("/api/stats"),
    refetchInterval: 15_000,
  });

  const { data: calls, isLoading: callsLoading } = useQuery<CallLog[]>({
    queryKey: ["/api/calls"],
    queryFn: () => fetchJSON("/api/calls?limit=8"),
    refetchInterval: 15_000,
  });

  const statItems = [
    {
      label: "Total Calls",
      value: stats?.total_calls ?? "—",
      icon: Phone,
      color: "text-primary",
    },
    {
      label: "Transferred",
      value: stats?.transferred ?? "—",
      icon: ArrowLeftRight,
      color: "text-purple-400",
    },
    {
      label: "Scheduled",
      value: stats?.scheduled ?? "—",
      icon: CalendarClock,
      color: "text-cyan-400",
    },
    {
      label: "Avg Duration",
      value: stats ? formatDuration(stats.avg_duration_seconds) : "—",
      icon: Clock,
      color: "text-amber-400",
    },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-0.5">AI receptionist activity overview</p>
        </div>
        <div className="live-indicator">
          <span className="status-dot active" />
          Live
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statItems.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="stat-card">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide">{label}</span>
              <Icon size={15} className={color} />
            </div>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold text-foreground mono">{value}</div>
            )}
          </div>
        ))}
      </div>

      {/* Recent calls */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Recent Calls</h2>
          <Link href="/calls">
            <a className="text-xs text-primary flex items-center gap-1 hover:underline">
              View all <ArrowRight size={11} />
            </a>
          </Link>
        </div>

        {callsLoading ? (
          <div className="p-4 space-y-3">
            {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : !calls?.length ? (
          <div className="py-12 text-center text-muted-foreground text-sm">
            <PhoneOff size={32} className="mx-auto mb-3 opacity-30" />
            No calls yet
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border">
                <th className="px-5 py-2.5 text-left font-medium">Caller</th>
                <th className="px-3 py-2.5 text-left font-medium">Time</th>
                <th className="px-3 py-2.5 text-left font-medium">Duration</th>
                <th className="px-3 py-2.5 text-left font-medium">Intent</th>
                <th className="px-3 py-2.5 text-left font-medium">Result</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {calls.map((call) => (
                <tr key={call.id} className="call-row border-b border-border last:border-0">
                  <td className="px-5 py-3 font-mono text-xs text-foreground">{call.caller_id}</td>
                  <td className="px-3 py-3 text-muted-foreground text-xs">{formatTime(call.started_at)}</td>
                  <td className="px-3 py-3 text-muted-foreground text-xs mono">{formatDuration(call.duration_seconds)}</td>
                  <td className="px-3 py-3 text-xs">
                    {call.intent ? (
                      <span className="text-muted-foreground capitalize">{call.intent_detail || call.intent}</span>
                    ) : <span className="text-muted-foreground/40">—</span>}
                  </td>
                  <td className="px-3 py-3">
                    <DispositionBadge disposition={call.disposition} />
                  </td>
                  <td className="px-3 py-3 text-right">
                    <Link href={`/calls/${call.call_id}`}>
                      <a className="text-xs text-primary hover:underline">View</a>
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
