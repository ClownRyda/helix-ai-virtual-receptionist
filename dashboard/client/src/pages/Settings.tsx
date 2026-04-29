import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Settings as SettingsIcon, Cpu, Mic, Volume2, Calendar, Clock, Building2, CheckCircle2, XCircle } from "lucide-react";
import { apiRequest, fetchJSON, queryClient } from "@/lib/queryClient";
import type { AgentConfig } from "@shared/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";

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
  const { toast } = useToast();
  const { data: config, isLoading } = useQuery<AgentConfig>({
    queryKey: ["/api/config"],
    queryFn: () => fetchJSON("/api/config"),
  });
  const [crm, setCrm] = useState({
    vtiger_enabled: false,
    vtiger_base_url: "",
    vtiger_username: "",
    vtiger_access_key: "",
    vtiger_default_module: "Contacts" as "Contacts" | "Leads",
  });
  const [healthMessage, setHealthMessage] = useState<{ ok: boolean; detail: string } | null>(null);

  useEffect(() => {
    if (!config) return;
    setCrm({
      vtiger_enabled: config.vtiger_enabled,
      vtiger_base_url: config.vtiger_base_url,
      vtiger_username: config.vtiger_username,
      vtiger_access_key: config.vtiger_access_key,
      vtiger_default_module: config.vtiger_default_module,
    });
  }, [config]);

  const saveCrmMutation = useMutation({
    mutationFn: async () =>
      apiRequest("PATCH", "/api/config", {
        vtiger_enabled: crm.vtiger_enabled,
        vtiger_base_url: crm.vtiger_base_url.trim(),
        vtiger_username: crm.vtiger_username.trim(),
        vtiger_access_key: crm.vtiger_access_key,
        vtiger_default_module: crm.vtiger_default_module,
      }),
    onSuccess: async () => {
      setHealthMessage(null);
      await queryClient.invalidateQueries({ queryKey: ["/api/config"] });
      toast({ title: "CRM settings saved" });
    },
    onError: (error: Error) => {
      toast({ title: "Could not save CRM settings", description: error.message, variant: "destructive" });
    },
  });

  const testMutation = useMutation({
    mutationFn: async () => fetchJSON<any>("/api/integrations/vtiger/health"),
    onSuccess: (result) => {
      if (result?.ok) {
        setHealthMessage({ ok: true, detail: "Connected" });
        return;
      }
      setHealthMessage({ ok: false, detail: result?.reason ?? "Connection failed" });
    },
    onError: (error: Error) => {
      setHealthMessage({ ok: false, detail: error.message });
    },
  });

  const crmDirty = !!config && (
    crm.vtiger_enabled !== config.vtiger_enabled ||
    crm.vtiger_base_url !== config.vtiger_base_url ||
    crm.vtiger_username !== config.vtiger_username ||
    crm.vtiger_access_key !== config.vtiger_access_key ||
    crm.vtiger_default_module !== config.vtiger_default_module
  );

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Settings</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Current agent configuration. Most settings remain read-only here; CRM can be edited below.
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

          <ConfigGroup title="CRM" icon={<Building2 size={14} />}>
            <div className="px-5 py-4 space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm text-foreground">Enable vTiger</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    Toggle the built-in vTiger integration for caller lookup and sync.
                  </div>
                </div>
                <Switch
                  checked={crm.vtiger_enabled}
                  onCheckedChange={(checked) => setCrm({ ...crm, vtiger_enabled: checked })}
                />
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <Input
                  placeholder="Base URL"
                  value={crm.vtiger_base_url}
                  onChange={(e) => setCrm({ ...crm, vtiger_base_url: e.target.value })}
                />
                <Input
                  placeholder="Username"
                  value={crm.vtiger_username}
                  onChange={(e) => setCrm({ ...crm, vtiger_username: e.target.value })}
                />
                <Input
                  type="password"
                  placeholder="Access Key"
                  value={crm.vtiger_access_key}
                  onChange={(e) => setCrm({ ...crm, vtiger_access_key: e.target.value })}
                />
                <Select
                  value={crm.vtiger_default_module}
                  onValueChange={(value: "Contacts" | "Leads") => setCrm({ ...crm, vtiger_default_module: value })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Default Module" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Contacts">Contacts</SelectItem>
                    <SelectItem value="Leads">Leads</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-xs min-h-5">
                  {healthMessage?.ok && <CheckCircle2 size={14} className="text-emerald-400" />}
                  {healthMessage && !healthMessage.ok && <XCircle size={14} className="text-rose-400" />}
                  {healthMessage && (
                    <span className={healthMessage.ok ? "text-emerald-300" : "text-rose-300"}>
                      {healthMessage.detail}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    onClick={() => testMutation.mutate()}
                    disabled={testMutation.isPending}
                  >
                    {testMutation.isPending ? "Testing..." : "Test Connection"}
                  </Button>
                  <Button
                    onClick={() => saveCrmMutation.mutate()}
                    disabled={!crmDirty || saveCrmMutation.isPending}
                  >
                    {saveCrmMutation.isPending ? "Saving..." : "Save CRM Settings"}
                  </Button>
                </div>
              </div>
            </div>
          </ConfigGroup>

          <div className="bg-muted/30 border border-border rounded-lg px-5 py-4 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground mb-2">To change settings:</p>
            <p>1. Edit <code className="bg-secondary px-1 py-0.5 rounded">agent/.env</code> or use the CRM form above</p>
            <p>2. Restart the agent: <code className="bg-secondary px-1 py-0.5 rounded">python agent/main.py</code></p>
            <p>3. Or with Docker: <code className="bg-secondary px-1 py-0.5 rounded">docker compose restart agent</code></p>
          </div>
        </div>
      )}
    </div>
  );
}
