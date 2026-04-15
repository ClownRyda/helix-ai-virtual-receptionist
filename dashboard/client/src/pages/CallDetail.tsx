import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "wouter";
import { ArrowLeft, Phone, Clock, CalendarClock, ArrowLeftRight } from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import type { CallLog } from "@shared/schema";
import DispositionBadge from "@/components/DispositionBadge";
import { Skeleton } from "@/components/ui/skeleton";

function formatDuration(s: number | null) {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function formatDateTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export default function CallDetail() {
  const params = useParams<{ callId: string }>();
  const callId = params.callId;

  const { data: call, isLoading } = useQuery<CallLog>({
    queryKey: ["/api/calls", callId],
    queryFn: () => fetchJSON(`/api/calls/${callId}`),
    enabled: !!callId,
  });

  if (isLoading) {
    return (
      <div className="p-6 max-w-3xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!call) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <Phone size={40} className="mx-auto mb-3 opacity-25" />
        <p>Call not found</p>
        <Link href="/calls"><a className="text-primary text-sm hover:underline mt-2 inline-block">← Back to logs</a></Link>
      </div>
    );
  }

  const lines = call.transcript?.split("\n").filter(Boolean) || [];

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      {/* Back */}
      <Link href="/calls">
        <a className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={13} /> Back to Call Logs
        </a>
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground mono">{call.caller_id}</h1>
          <p className="text-xs text-muted-foreground mt-1 mono">{call.call_id}</p>
        </div>
        <DispositionBadge disposition={call.disposition} />
      </div>

      {/* Meta grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Started", value: formatDateTime(call.started_at), icon: Clock },
          { label: "Ended", value: formatDateTime(call.ended_at), icon: Clock },
          { label: "Duration", value: formatDuration(call.duration_seconds), icon: Clock },
          { label: "Intent", value: call.intent_detail || call.intent || "—", icon: Phone },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="stat-card">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Icon size={11} className="text-muted-foreground" />
              <span className="text-xs text-muted-foreground">{label}</span>
            </div>
            <div className="text-sm font-medium text-foreground capitalize">{value}</div>
          </div>
        ))}
      </div>

      {/* Transfer info */}
      {call.transferred_to && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground bg-card border border-border rounded-lg px-4 py-3">
          <ArrowLeftRight size={14} className="text-purple-400" />
          <span>Transferred to extension <span className="text-foreground font-mono font-semibold">{call.transferred_to}</span></span>
        </div>
      )}

      {/* Appointment */}
      {call.appointment_id && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground bg-card border border-border rounded-lg px-4 py-3">
          <CalendarClock size={14} className="text-cyan-400" />
          <span>Scheduled — Google Calendar event <span className="text-foreground font-mono text-xs">{call.appointment_id}</span></span>
        </div>
      )}

      {/* Transcript */}
      <div>
        <h2 className="text-sm font-semibold text-foreground mb-3">Transcript</h2>
        {lines.length === 0 ? (
          <div className="transcript-block text-muted-foreground/50">No transcript available</div>
        ) : (
          <div className="transcript-block space-y-2">
            {lines.map((line, i) => {
              const isAgent = line.startsWith("Agent:");
              const isCaller = line.startsWith("Caller:");
              return (
                <div key={i} className={`${isAgent ? "text-primary/80" : isCaller ? "text-foreground" : "text-muted-foreground"}`}>
                  {isAgent && <span className="text-primary/50 mr-1">▶</span>}
                  {isCaller && <span className="text-amber-500/60 mr-1">◀</span>}
                  {line}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Notes */}
      {call.notes && (
        <div>
          <h2 className="text-sm font-semibold text-foreground mb-2">Notes</h2>
          <p className="text-sm text-muted-foreground bg-card border border-border rounded-lg px-4 py-3">{call.notes}</p>
        </div>
      )}
    </div>
  );
}
