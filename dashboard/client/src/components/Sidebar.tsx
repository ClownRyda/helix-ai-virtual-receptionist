import { Link, useLocation } from "wouter";
import { Phone, LayoutDashboard, GitMerge, CalendarClock, Settings, Radio } from "lucide-react";

const nav = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/calls", label: "Call Logs", icon: Phone },
  { href: "/routing", label: "Routing Rules", icon: GitMerge },
  { href: "/appointments", label: "Appointments", icon: CalendarClock },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const [location] = useLocation();

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2.5">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-label="PBX Assistant">
            <rect width="28" height="28" rx="6" fill="hsl(188 72% 42% / 0.15)" />
            <circle cx="14" cy="14" r="5" stroke="hsl(188 72% 42%)" strokeWidth="1.5" fill="none" />
            <path d="M14 9V7M14 21v-2M9 14H7M21 14h-2" stroke="hsl(188 72% 42%)" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="14" cy="14" r="2" fill="hsl(188 72% 42%)" />
          </svg>
          <div>
            <div className="text-sm font-semibold text-foreground leading-none">PBX Assistant</div>
            <div className="text-xs text-muted-foreground mt-0.5">AI Receptionist</div>
          </div>
        </div>
      </div>

      {/* Status */}
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

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border">
        <div className="text-xs text-muted-foreground space-y-1">
          <div className="flex items-center gap-1.5">
            <Radio size={11} />
            <span>Asterisk ARI</span>
            <span className="status-dot online ml-auto" />
          </div>
          <div className="flex items-center gap-1.5">
            <span>Ollama LLM</span>
            <span className="status-dot online ml-auto" />
          </div>
          <div className="flex items-center gap-1.5">
            <span>Whisper STT</span>
            <span className="status-dot online ml-auto" />
          </div>
        </div>
      </div>
    </aside>
  );
}
