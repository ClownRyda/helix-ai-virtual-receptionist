import { Link, useLocation } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { Phone, LayoutDashboard, GitMerge, CalendarClock, Settings, Radio, Voicemail, UsersRound } from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import type { HealthStatus } from "@shared/schema";

const nav = [
  { href: "/",             label: "Dashboard",    icon: LayoutDashboard },
  { href: "/calls",        label: "Call Logs",    icon: Phone },
  { href: "/routing",      label: "Routing Rules",icon: GitMerge },
  { href: "/agents",       label: "Agents",       icon: UsersRound },
  { href: "/appointments", label: "Appointments", icon: CalendarClock },
  { href: "/voicemails",   label: "Voicemails",   icon: Voicemail },
  { href: "/settings",     label: "Settings",     icon: Settings },
];

export default function Sidebar() {
  const [location] = useLocation();

  const { data: health } = useQuery<HealthStatus>({
    queryKey: ["/api/health"],
    queryFn: () => fetchJSON("/api/health"),
    refetchInterval: 30_000,
  });

  const version = (health as any)?.version ?? "…";
  const ttsEngine = (health as any)?.tts_engine ?? "TTS";

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2.5">
          {/* Helix waveform icon */}
          <svg width="30" height="30" viewBox="0 0 30 30" fill="none" aria-label="Helix AI">
            <rect width="30" height="30" rx="7" fill="hsl(188 72% 42% / 0.15)" />
            <rect x="6"  y="13" width="2.5" height="4"  rx="1.2" fill="hsl(188 72% 42% / 0.5)" />
            <rect x="10" y="10" width="2.5" height="10" rx="1.2" fill="hsl(188 72% 42% / 0.75)" />
            <rect x="14" y="7"  width="2.5" height="16" rx="1.2" fill="hsl(188 72% 42%)" />
            <rect x="18" y="10" width="2.5" height="10" rx="1.2" fill="hsl(188 72% 42% / 0.75)" />
            <rect x="22" y="13" width="2.5" height="4"  rx="1.2" fill="hsl(188 72% 42% / 0.5)" />
          </svg>
          <div>
            <div className="text-sm font-semibold text-foreground leading-none">Helix AI</div>
            <div className="text-xs text-muted-foreground mt-0.5">Virtual Receptionist</div>
          </div>
        </div>
      </div>

      {/* Status pill */}
      <div className="px-5 py-3 border-b border-border">
        <div className="live-indicator">
          <span className="status-dot active" />
          Agent Online
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = location === href || (href !== "/" && location.startsWith(href));
          return (
            <Link key={href} href={href}>
              <a
                data-testid={`nav-${label.toLowerCase().replace(/\s+/g, "-")}`}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                  active
                    ? "bg-primary/15 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                }`}
              >
                <Icon size={15} strokeWidth={active ? 2.5 : 1.75} />
                {label}
              </a>
            </Link>
          );
        })}
      </nav>

      {/* Service health footer — version + TTS engine pulled from /api/health */}
      <div className="px-5 py-4 border-t border-border space-y-2">
        <div className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Services</div>
        {[
          { label: "Asterisk ARI", icon: Radio },
          { label: "Ollama LLM",   icon: null },
          { label: "Whisper STT",  icon: null },
          { label: ttsEngine,      icon: null },
        ].map(({ label }) => (
          <div key={label} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="flex-1">{label}</span>
            <span className="status-dot online" />
          </div>
        ))}
        <div className="pt-2 text-xs text-muted-foreground/50 font-mono">v{version}</div>
      </div>
    </aside>
  );
}
