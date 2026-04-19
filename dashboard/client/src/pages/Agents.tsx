import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Languages, PhoneCall, Plus, UserRound, UsersRound } from "lucide-react";
import { apiRequest, fetchJSON, queryClient } from "@/lib/queryClient";
import type { AgentAvailabilityState, AgentLanguage, HumanAgent } from "@shared/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";

const LANGUAGE_OPTIONS: { value: AgentLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "it", label: "Italian" },
  { value: "he", label: "Hebrew" },
  { value: "ro", label: "Romanian" },
];

const STATE_OPTIONS: { value: AgentAvailabilityState; label: string }[] = [
  { value: "available", label: "Available" },
  { value: "busy", label: "Busy" },
  { value: "break", label: "Break" },
  { value: "offline", label: "Offline" },
];

function fmtRelative(iso: string | null) {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statePill(state: AgentAvailabilityState) {
  switch (state) {
    case "available":
      return "bg-emerald-500/10 text-emerald-300 border-emerald-500/20";
    case "busy":
      return "bg-amber-500/10 text-amber-300 border-amber-500/20";
    case "break":
      return "bg-sky-500/10 text-sky-300 border-sky-500/20";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

export default function Agents() {
  const { toast } = useToast();
  const [adding, setAdding] = useState(false);
  const [newAgent, setNewAgent] = useState({
    agent_id: "",
    display_name: "",
    extension: "",
    preferred_language: "en" as AgentLanguage,
    availability_state: "available" as AgentAvailabilityState,
    supported_languages: "en",
    assigned_queues: "",
  });

  const { data: agents, isLoading } = useQuery<HumanAgent[]>({
    queryKey: ["/api/agents"],
    queryFn: () => fetchJSON("/api/agents"),
    refetchInterval: 15_000,
  });

  const registerMutation = useMutation({
    mutationFn: async () =>
      apiRequest("POST", "/api/agents/register", {
        agent_id: newAgent.agent_id.trim(),
        display_name: newAgent.display_name.trim(),
        extension: newAgent.extension.trim(),
        preferred_language: newAgent.preferred_language,
        availability_state: newAgent.availability_state,
        supported_languages: newAgent.supported_languages
          .split(",")
          .map((item) => item.trim().toLowerCase())
          .filter(Boolean),
        assigned_queues: newAgent.assigned_queues
          .split(",")
          .map((item) => item.trim().toLowerCase())
          .filter(Boolean),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["/api/agents"] });
      setAdding(false);
      setNewAgent({
        agent_id: "",
        display_name: "",
        extension: "",
        preferred_language: "en",
        availability_state: "available",
        supported_languages: "en",
        assigned_queues: "",
      });
      toast({ title: "Agent saved" });
    },
    onError: (error: Error) => {
      toast({ title: "Could not save agent", description: error.message, variant: "destructive" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      agentId,
      patch,
    }: {
      agentId: string;
      patch: Partial<Pick<HumanAgent, "availability_state" | "preferred_language">>;
    }) => apiRequest("PATCH", `/api/agents/${agentId}`, patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["/api/agents"] });
    },
    onError: (error: Error) => {
      toast({ title: "Could not update agent", description: error.message, variant: "destructive" });
    },
  });

  const counts = useMemo(() => {
    const rows = agents ?? [];
    return {
      total: rows.length,
      available: rows.filter((agent) => agent.availability_state === "available").length,
      busy: rows.filter((agent) => agent.availability_state === "busy").length,
      break: rows.filter((agent) => agent.availability_state === "break").length,
    };
  }, [agents]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Agents</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Register human agents, set their language, and control live handoff availability.
          </p>
        </div>
        <Button size="sm" className="gap-1.5" onClick={() => setAdding((open) => !open)}>
          <Plus size={13} /> {adding ? "Close" : "Add Agent"}
        </Button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Registered", value: counts.total, icon: UsersRound, tone: "text-primary" },
          { label: "Available", value: counts.available, icon: PhoneCall, tone: "text-emerald-300" },
          { label: "Busy", value: counts.busy, icon: UserRound, tone: "text-amber-300" },
          { label: "On Break", value: counts.break, icon: Languages, tone: "text-sky-300" },
        ].map(({ label, value, icon: Icon, tone }) => (
          <div key={label} className="stat-card">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide">{label}</span>
              <Icon size={13} className={tone} />
            </div>
            <div className="text-2xl font-bold text-foreground mono">{value}</div>
          </div>
        ))}
      </div>

      {adding && (
        <div className="bg-card border border-border rounded-lg p-5 space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-foreground">New Agent</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Agents can also sign in from their phone with `*55`, but this form is the quickest way to seed the pool.
            </p>
          </div>

          <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-3">
            <Input
              placeholder="Agent ID"
              value={newAgent.agent_id}
              onChange={(e) => setNewAgent({ ...newAgent, agent_id: e.target.value })}
            />
            <Input
              placeholder="Display name"
              value={newAgent.display_name}
              onChange={(e) => setNewAgent({ ...newAgent, display_name: e.target.value })}
            />
            <Input
              placeholder="Extension"
              value={newAgent.extension}
              onChange={(e) => setNewAgent({ ...newAgent, extension: e.target.value })}
            />
            <select
              value={newAgent.preferred_language}
              onChange={(e) => setNewAgent({ ...newAgent, preferred_language: e.target.value as AgentLanguage })}
              className="h-10 rounded-md border border-border bg-background px-3 text-sm text-foreground"
            >
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <Input
              placeholder="Supported languages (comma-separated)"
              value={newAgent.supported_languages}
              onChange={(e) => setNewAgent({ ...newAgent, supported_languages: e.target.value })}
              className="md:col-span-2"
            />
            <Input
              placeholder="Assigned queues (sales,support,operator)"
              value={newAgent.assigned_queues}
              onChange={(e) => setNewAgent({ ...newAgent, assigned_queues: e.target.value })}
              className="md:col-span-2"
            />
          </div>

          <div className="flex justify-end">
            <Button
              onClick={() => registerMutation.mutate()}
              disabled={!newAgent.agent_id.trim() || !newAgent.display_name.trim() || !newAgent.extension.trim() || registerMutation.isPending}
            >
              Save Agent
            </Button>
          </div>
        </div>
      )}

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Agent Pool</h2>
        </div>

        {isLoading ? (
          <div className="p-4 space-y-3">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        ) : !agents?.length ? (
          <div className="py-16 text-center text-sm text-muted-foreground">
            <UsersRound size={32} className="mx-auto mb-3 opacity-25" />
            No agents registered yet
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border bg-muted/30">
                <th className="px-5 py-3 text-left font-medium">Agent</th>
                <th className="px-3 py-3 text-left font-medium">Extension</th>
                <th className="px-3 py-3 text-left font-medium">Preferred Language</th>
                <th className="px-3 py-3 text-left font-medium">Queues</th>
                <th className="px-3 py-3 text-left font-medium">State</th>
                <th className="px-3 py-3 text-left font-medium">Last Offered</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr key={agent.agent_id} className="border-b border-border last:border-0">
                  <td className="px-5 py-3">
                    <div className="text-sm font-medium text-foreground">{agent.display_name}</div>
                    <div className="text-xs text-muted-foreground mono mt-0.5">{agent.agent_id}</div>
                  </td>
                  <td className="px-3 py-3 text-xs font-mono text-primary">{agent.extension}</td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2">
                      <select
                        value={agent.preferred_language}
                        onChange={(e) =>
                          updateMutation.mutate({
                            agentId: agent.agent_id,
                            patch: { preferred_language: e.target.value as AgentLanguage },
                          })
                        }
                        className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground"
                      >
                        {LANGUAGE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <div className="text-xs text-muted-foreground">
                        {agent.supported_languages.join(", ") || "—"}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground">
                    {agent.assigned_queues.length ? agent.assigned_queues.join(", ") : "general"}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${statePill(agent.availability_state)}`}>
                        {agent.availability_state}
                      </span>
                      <select
                        value={agent.availability_state}
                        onChange={(e) =>
                          updateMutation.mutate({
                            agentId: agent.agent_id,
                            patch: { availability_state: e.target.value as AgentAvailabilityState },
                          })
                        }
                        className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground"
                      >
                        {STATE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground mono">
                    {fmtRelative(agent.last_offered_at)}
                    {agent.current_call_id ? (
                      <div className="text-[11px] text-amber-300 mt-1">{agent.current_call_id}</div>
                    ) : null}
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
