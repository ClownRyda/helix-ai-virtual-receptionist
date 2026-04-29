import { useQuery } from "@tanstack/react-query";
import { Settings as SettingsIcon, Cpu, Mic, Volume2, Calendar, Clock } from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import type { AgentConfig } from "@shared/schema";
import { Skeleton } from "@/components/ui/skeleton";

interface ConfigGroupProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}

function ConfigGroup({ title, icon, children }: ConfigGroupProps) {
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3.5 border-b border-border">
        <span className="text-primary">{icon}</span>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      </div>
      <div className="divide-y divide-border">{children}</div>
    </div>
  );
}

interface ConfigRowProps {
  label: string;
  value: React.ReactNode;
  description?: string;
}

function ConfigRow({ label, value, description }: ConfigRowProps) {
  return (
    <div className="flex items-center justify-between px-5 py-3.5 gap-4">
      <div>
        <div className="text-sm text-foreground">{label}</div>
        {description && <div className="text-xs text-muted-foreground mt-0.5">{description}</div>}
      </div>
      <div className="text-sm mono font-medium text-primary shrink-0">{value}</div>
    </div>
  );
}

export default function Settings() {
  const { data: config, isLoading } = useQuery<AgentConfig>({
    queryKey: ["/api/config"],
    queryFn: () => fetchJSON("/api/config"),
  });

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Settings</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Read-only view of current agent configuration. Edit via <code className="text-xs bg-secondary px-1 py-0.5 rounded">agent/.env</code>
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-40 w-full" />)}
        </div>
      ) : !config ? (
        <div className="text-center text-muted-foreground py-12 text-sm">
          Could not load config — is the agent running?
        </div>
      ) : (
        <div className="space-y-4">
          <ConfigGroup title="Business" icon={<SettingsIcon size={14} />}>
            <ConfigRow label="Business Name" value={config.business_name} />
            <ConfigRow label="Agent Name" value={config.agent_name} description="How the AI introduces itself" />
            <ConfigRow label="Timezone" value={config.business_timezone} />
          </ConfigGroup>

          <ConfigGroup title="Business Hours" icon={<Clock size={14} />}>
            <ConfigRow
              label="Operating Hours"
              value={`${config.business_hours_start}:00 – ${config.business_hours_end}:00`}
              description="Slots are only offered within these hours"
            />
            <ConfigRow
              label="Slot Duration"
              value={`${config.appointment_slot_minutes} min`}
              description="Length of each scheduled callback"
            />
            <ConfigRow
              label="Lookahead"
              value={`${config.availability_lookahead_days} days`}
              description="How far ahead to offer slots"
            />
          </ConfigGroup>

          <ConfigGroup title="Speech-to-Text" icon={<Mic size={14} />}>
            <ConfigRow
              label="Whisper Model"
              value={config.whisper_model}
              description="Larger models are more accurate but slower"
            />
          </ConfigGroup>

          <ConfigGroup title="Language Model" icon={<Cpu size={14} />}>
            <ConfigRow
              label="Ollama Model"
              value={config.ollama_model}
              description="Used for intent detection and conversation"
            />
          </ConfigGroup>

          <ConfigGroup title="Text-to-Speech" icon={<Volume2 size={14} />}>
            <ConfigRow
              label="Kokoro Voice (EN)"
              value={config.kokoro_voice_en}
              description="Primary English neural TTS voice"
            />
          </ConfigGroup>

          <ConfigGroup title="Google Calendar" icon={<Calendar size={14} />}>
            <ConfigRow
              label="Calendar ID"
              value={config.google_calendar_id}
              description="Calendar used for free/busy lookups and event creation"
            />
          </ConfigGroup>

          <div className="bg-muted/30 border border-border rounded-lg px-5 py-4 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground mb-2">To change settings:</p>
            <p>1. Edit <code className="bg-secondary px-1 py-0.5 rounded">agent/.env</code></p>
            <p>2. Restart the agent: <code className="bg-secondary px-1 py-0.5 rounded">python agent/main.py</code></p>
            <p>3. Or with Docker: <code className="bg-secondary px-1 py-0.5 rounded">docker compose restart agent</code></p>
          </div>
        </div>
      )}
    </div>
  );
}
