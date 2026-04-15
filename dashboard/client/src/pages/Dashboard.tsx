import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import {
  Phone, ArrowRight, CalendarClock, ArrowLeftRight, PhoneOff,
  Clock, GitMerge, Mic, Cpu, Volume2, Globe, ShieldCheck,
  Hash, Voicemail, FileText, HelpCircle, Building2,
  CheckCircle2, XCircle, AlertTriangle, CalendarX,
} from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import type { CallStats, CallLog, AgentConfig, RoutingRule, Appointment, HealthStatus, Holiday } from "@shared/schema";
import DispositionBadge from "@/components/DispositionBadge";
import { Skeleton } from "@/components/ui/skeleton";

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(s: number | null) {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function fmtTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function isOpenNow(config: AgentConfig): boolean {
  const tz = config.business_timezone;
  try {
    const now = new Date().toLocaleString("en-US", { timeZone: tz, hour: "numeric", hour12: false, weekday: "short" });
    const parts = now.split(", ");
    const dow = parts[0]; // "Mon", "Tue", etc.
    const hour = parseInt(parts[1] ?? "0");
    const isWeekday = !["Sat", "Sun"].includes(dow);
    return isWeekday && hour >= config.business_hours_start && hour < config.business_hours_end;
  } catch {
    return false;
  }
}

// ── Sub-components ─────────────────────────────────────────────────────────

function SectionHeader({ title, linkHref, linkLabel }: { title: string; linkHref?: string; linkLabel?: string }) {
  return (
    <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      {linkHref && (
        <Link href={linkHref}>
          <a className="text-xs text-primary flex items-center gap-1 hover:underline">
            {linkLabel ?? "View all"} <ArrowRight size={11} />
          </a>
        </Link>
      )}
    </div>
  );
}

function Flag({ on, label }: { on: boolean; label: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 px-5 border-b border-border last:border-0">
      <span className="text-sm text-foreground">{label}</span>
      {on
        ? <span className="flex items-center gap-1.5 text-xs text-emerald-400"><CheckCircle2 size={13} /> Enabled</span>
        : <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><XCircle size={13} /> Off</span>}
    </div>
  );
}

function InfoRow({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2.5 px-5 border-b border-border last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm font-medium text-foreground ${mono ? "font-mono text-xs" : ""}`}>{value}</span>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: stats, isLoading: statsLoading } = useQuery<CallStats>({
    queryKey: ["/api/stats"],
    queryFn: () => fetchJSON("/api/stats"),
    refetchInterval: 15_000,
  });

  const { data: calls, isLoading: callsLoading } = useQuery<CallLog[]>({
    queryKey: ["/api/calls"],
    queryFn: () => fetchJSON("/api/calls?limit=6"),
    refetchInterval: 15_000,
  });

  const { data: config } = useQuery<AgentConfig>({
    queryKey: ["/api/config"],
    queryFn: () => fetchJSON("/api/config"),
  });

  const { data: rules } = useQuery<RoutingRule[]>({
    queryKey: ["/api/rules"],
    queryFn: () => fetchJSON("/api/rules"),
  });

  const { data: appointments } = useQuery<Appointment[]>({
    queryKey: ["/api/appointments"],
    queryFn: () => fetchJSON("/api/appointments"),
  });

  const { data: holidays } = useQuery<Holiday[]>({
    queryKey: ["/api/holidays"],
    queryFn: () => fetchJSON("/api/holidays"),
  });

  const { data: health } = useQuery<HealthStatus>({
    queryKey: ["/api/health"],
    queryFn: () => fetchJSON("/api/health"),
    refetchInterval: 30_000,
  });

  const open = config ? isOpenNow(config) : null;
  const nextAppts = appointments
    ?.filter(a => new Date(a.scheduled_at) > new Date())
    .sort((a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime())
    .slice(0, 3);
  const activeRules = rules?.filter(r => r.active) ?? [];
  const upcomingHolidays = holidays
    ?.filter(h => h.active && new Date(h.date + "T00:00:00") >= new Date())
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 3) ?? [];

  // Build hourly label
  const hoursLabel = config
    ? (() => {
        const fmt12 = (h: number) => {
          const period = h >= 12 ? "PM" : "AM";
          const h12 = h % 12 === 0 ? 12 : h % 12;
          return `${h12}:00 ${period}`;
        };
        return `${fmt12(config.business_hours_start)} – ${fmt12(config.business_hours_end)}`;
      })()
    : "—";

  const statCards = [
    { label: "Total Calls", value: stats?.total_calls ?? "—", icon: Phone, color: "text-primary" },
    { label: "Transferred", value: stats?.transferred ?? "—", icon: ArrowLeftRight, color: "text-purple-400" },
    { label: "Scheduled", value: stats?.scheduled ?? "—", icon: CalendarClock, color: "text-cyan-400" },
    { label: "After Hours", value: stats?.after_hours ?? "—", icon: Clock, color: "text-amber-400" },
    { label: "Voicemail", value: stats?.voicemail ?? "—", icon: Voicemail, color: "text-rose-400" },
    { label: "Avg Duration", value: stats ? fmt(stats.avg_duration_seconds) : "—", icon: Clock, color: "text-slate-400" },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">
            {config?.business_name ?? "Helix AI"} — Receptionist
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {config?.agent_name ?? "AI"} · {config?.business_timezone ?? ""}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {open !== null && (
            <span className={`flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide ${open ? "text-emerald-400" : "text-amber-400"}`}>
              <span className={`status-dot ${open ? "online" : "active"}`} />
              {open ? "Open" : "Closed"}
            </span>
          )}
          <div className="live-indicator">
            <span className="status-dot active" />
            Live
          </div>
        </div>
      </div>

      {/* ── Stat cards ── */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
        {statCards.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="stat-card">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide leading-tight">{label}</span>
              <Icon size={13} className={color} />
            </div>
            {statsLoading
              ? <Skeleton className="h-7 w-12" />
              : <div className="text-2xl font-bold text-foreground mono">{value}</div>}
          </div>
        ))}
      </div>

      {/* ── Main 2-col grid ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* Left col (2/3) */}
        <div className="lg:col-span-2 space-y-5">

          {/* Recent calls */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="Recent Calls" linkHref="/calls" />
            {callsLoading ? (
              <div className="p-4 space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
            ) : !calls?.length ? (
              <div className="py-10 text-center text-muted-foreground text-sm">
                <PhoneOff size={28} className="mx-auto mb-3 opacity-30" />
                No calls yet
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border">
                    <th className="px-5 py-2.5 text-left font-medium">Caller</th>
                    <th className="px-3 py-2.5 text-left font-medium">Time</th>
                    <th className="px-3 py-2.5 text-left font-medium">Dur</th>
                    <th className="px-3 py-2.5 text-left font-medium">Intent</th>
                    <th className="px-3 py-2.5 text-left font-medium">Result</th>
                    <th className="px-3 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {calls.map((call) => (
                    <tr key={call.id} className="call-row border-b border-border last:border-0">
                      <td className="px-5 py-2.5 font-mono text-xs text-foreground">{call.caller_id}</td>
                      <td className="px-3 py-2.5 text-muted-foreground text-xs">{fmtTime(call.started_at)}</td>
                      <td className="px-3 py-2.5 text-muted-foreground text-xs mono">{fmt(call.duration_seconds)}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground capitalize">{call.intent_detail || call.intent || "—"}</td>
                      <td className="px-3 py-2.5"><DispositionBadge disposition={call.disposition} /></td>
                      <td className="px-3 py-2.5 text-right">
                        <Link href={`/calls/${call.call_id}`}><a className="text-xs text-primary hover:underline">View</a></Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Routing rules snapshot */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="Active Routing Rules" linkHref="/routing" linkLabel="Manage" />
            {!activeRules.length ? (
              <div className="px-5 py-6 text-sm text-muted-foreground">No active rules</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border">
                    <th className="px-5 py-2 text-left font-medium">Keyword</th>
                    <th className="px-3 py-2 text-left font-medium">Extension</th>
                    <th className="px-3 py-2 text-left font-medium">Description</th>
                    <th className="px-3 py-2 text-left font-medium">Agent Lang</th>
                    <th className="px-3 py-2 text-left font-medium">Priority</th>
                  </tr>
                </thead>
                <tbody>
                  {activeRules.map((r) => (
                    <tr key={r.id} className="call-row border-b border-border last:border-0">
                      <td className="px-5 py-2.5 font-mono text-xs text-primary">{r.keyword}</td>
                      <td className="px-3 py-2.5 font-mono text-xs text-foreground">{r.extension}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{r.description || "—"}</td>
                      <td className="px-3 py-2.5">
                        <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${r.agent_lang === "es" ? "bg-amber-900/40 text-amber-300" : "bg-primary/10 text-primary"}`}>
                          {r.agent_lang ?? "en"}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground mono">{r.priority}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Upcoming appointments */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="Upcoming Appointments" linkHref="/appointments" />
            {!nextAppts?.length ? (
              <div className="px-5 py-6 text-sm text-muted-foreground">No upcoming appointments</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border">
                    <th className="px-5 py-2 text-left font-medium">Name</th>
                    <th className="px-3 py-2 text-left font-medium">Phone</th>
                    <th className="px-3 py-2 text-left font-medium">When</th>
                    <th className="px-3 py-2 text-left font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {nextAppts.map((a) => (
                    <tr key={a.id} className="call-row border-b border-border last:border-0">
                      <td className="px-5 py-2.5 text-sm text-foreground">{a.caller_name}</td>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{a.caller_phone}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{fmtTime(a.scheduled_at)}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{a.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right col (1/3) */}
        <div className="space-y-5">

          {/* System status */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="System Status" />
            <div className="divide-y divide-border">
              {[
                { label: "Asterisk ARI", ok: true },
                { label: "Ollama LLM", ok: true },
                { label: "Whisper STT", ok: true },
                { label: "Piper TTS", ok: true },
                { label: "Google Calendar", ok: true },
              ].map(({ label, ok }) => (
                <div key={label} className="flex items-center justify-between px-5 py-2.5">
                  <span className="text-sm text-foreground">{label}</span>
                  <span className={`status-dot ${ok ? "online" : "offline"}`} />
                </div>
              ))}
              <div className="flex items-center justify-between px-5 py-2.5">
                <span className="text-sm text-foreground">Version</span>
                <span className="text-xs font-mono text-primary">{health?.version ?? "v1.2"}</span>
              </div>
            </div>
          </div>

          {/* Business hours */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="Business Hours" />
            <div className="divide-y divide-border">
              <div className="flex items-center justify-between px-5 py-3">
                <span className="text-sm text-muted-foreground">Status now</span>
                {open === null
                  ? <Skeleton className="h-5 w-16" />
                  : open
                    ? <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 size={13} /> Open</span>
                    : <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-400"><AlertTriangle size={13} /> Closed</span>}
              </div>
              <InfoRow label="Hours" value={hoursLabel} />
              <InfoRow label="Timezone" value={config?.business_timezone ?? "—"} mono />
              <InfoRow label="After-hours mode" value={config?.after_hours_mode ?? "—"} mono />
              <InfoRow label="Operator ext" value={config?.operator_extension ?? "—"} mono />
            </div>
          </div>

          {/* AI config */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="AI Configuration" linkHref="/settings" linkLabel="All settings" />
            <div className="divide-y divide-border">
              <InfoRow label="Agent name" value={config?.agent_name ?? "—"} />
              <InfoRow label="LLM" value={config?.ollama_model ?? "—"} mono />
              <InfoRow label="STT" value={config?.whisper_model ?? "—"} mono />
              <InfoRow label="TTS (EN)" value={config?.piper_model ?? "—"} mono />
              <InfoRow label="Max retries" value={config ? `${config.max_retries} tries` : "—"} />
              <InfoRow label="Silence timeout" value={config ? `${config.silence_timeout_sec}s` : "—"} />
            </div>
          </div>

          {/* Feature flags */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="Feature Flags" />
            {!config ? (
              <div className="p-4 space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
            ) : (
              <div className="divide-y divide-border">
                <Flag on={config.dtmf_enabled} label="DTMF keypress menu" />
                <Flag on={!!config.vip_callers} label="VIP caller bypass" />
                <Flag on={config.voicemail_enabled} label="Voicemail recording" />
                <Flag on={config.voicemail_transcribe && config.voicemail_enabled} label="Voicemail transcription" />
                <Flag on={config.call_summary_enabled} label="AI call summaries" />
                <Flag on={config.faq_enabled} label="FAQ knowledge base" />
              </div>
            )}
          </div>

          {/* Upcoming holidays */}
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <SectionHeader title="Upcoming Holidays" />
            {!upcomingHolidays.length ? (
              <div className="px-5 py-4 text-sm text-muted-foreground flex items-center gap-2">
                <CalendarX size={14} /> None scheduled
              </div>
            ) : (
              <div className="divide-y divide-border">
                {upcomingHolidays.map((h) => (
                  <div key={h.id} className="flex items-center justify-between px-5 py-2.5">
                    <span className="text-sm text-foreground">{h.name}</span>
                    <span className="text-xs font-mono text-muted-foreground">{fmtDate(h.date)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
