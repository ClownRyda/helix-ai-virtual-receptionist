import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Pause, Play, Plus, Radio, Trash2, CheckCircle2, Archive, Info } from "lucide-react";
import { apiRequest, fetchJSON, queryClient } from "@/lib/queryClient";
import type { Campaign, CampaignStatus } from "@shared/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useToast } from "@/hooks/use-toast";

function fmtTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function statusTone(status: CampaignStatus) {
  switch (status) {
    case "active":
      return "bg-emerald-500/10 text-emerald-300 border-emerald-500/20";
    case "paused":
      return "bg-amber-500/10 text-amber-300 border-amber-500/20";
    case "completed":
      return "bg-sky-500/10 text-sky-300 border-sky-500/20";
    case "archived":
      return "bg-muted text-muted-foreground border-border";
    default:
      return "bg-primary/10 text-primary border-primary/20";
  }
}

export default function Campaigns() {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    description: "",
    caller_id: "",
    script: "",
    target_list: "",
  });

  const { data: campaigns, isLoading } = useQuery<Campaign[]>({
    queryKey: ["/api/campaigns"],
    queryFn: () => fetchJSON("/api/campaigns"),
    refetchInterval: 15_000,
  });

  const selected = useMemo(
    () => campaigns?.find((campaign) => campaign.campaign_id === selectedId) ?? campaigns?.[0] ?? null,
    [campaigns, selectedId],
  );

  const createMutation = useMutation({
    mutationFn: async () => {
      const targets = form.target_list
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      return apiRequest("POST", "/api/campaigns", {
        name: form.name.trim(),
        description: form.description.trim(),
        caller_id: form.caller_id.trim(),
        script: form.script,
        target_list: JSON.stringify(targets),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["/api/campaigns"] });
      setOpen(false);
      setForm({ name: "", description: "", caller_id: "", script: "", target_list: "" });
      toast({ title: "Campaign created" });
    },
    onError: (error: Error) => {
      toast({ title: "Could not create campaign", description: error.message, variant: "destructive" });
    },
  });

  const actionMutation = useMutation({
    mutationFn: async ({ campaignId, action }: { campaignId: string; action: "start" | "pause" | "complete" | "delete" }) => {
      if (action === "delete") {
        return apiRequest("DELETE", `/api/campaigns/${campaignId}`);
      }
      return apiRequest("POST", `/api/campaigns/${campaignId}/${action}`);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["/api/campaigns"] });
    },
    onError: (error: Error) => {
      toast({ title: "Campaign action failed", description: error.message, variant: "destructive" });
    },
  });

  const counts = useMemo(() => {
    const rows = campaigns ?? [];
    return {
      total: rows.length,
      active: rows.filter((campaign) => campaign.status === "active").length,
      paused: rows.filter((campaign) => campaign.status === "paused").length,
      completed: rows.filter((campaign) => campaign.status === "completed").length,
    };
  }, [campaigns]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Campaigns</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Track outbound campaign state, targets, and operator-facing notes.
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus size={13} /> Create Campaign
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>Create Campaign</DialogTitle>
            </DialogHeader>
            <div className="grid gap-3 py-2">
              <Input
                placeholder="Campaign name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
              <Input
                placeholder="Caller ID (optional)"
                value={form.caller_id}
                onChange={(e) => setForm({ ...form, caller_id: e.target.value })}
              />
              <Textarea
                placeholder="Description"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
              />
              <Textarea
                placeholder="Script / notes"
                value={form.script}
                onChange={(e) => setForm({ ...form, script: e.target.value })}
                rows={5}
              />
              <Textarea
                placeholder={"Target numbers — one per line\n1001\n1002\n1003"}
                value={form.target_list}
                onChange={(e) => setForm({ ...form, target_list: e.target.value })}
                rows={6}
                className="font-mono text-xs"
              />
              <div className="flex justify-end">
                <Button
                  onClick={() => createMutation.mutate()}
                  disabled={!form.name.trim() || !form.target_list.trim() || createMutation.isPending}
                >
                  Save Campaign
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <Alert className="border-primary/20 bg-primary/5">
        <Info size={16} className="text-primary" />
        <AlertTitle>Campaign runner is scaffolded</AlertTitle>
        <AlertDescription>
          Campaigns currently track state and metrics but do not yet originate calls automatically. Use the Outbound Calls page to place individual test calls. Campaign runner integration is planned.
        </AlertDescription>
      </Alert>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Campaigns", value: counts.total, icon: Radio, tone: "text-primary" },
          { label: "Active", value: counts.active, icon: Play, tone: "text-emerald-300" },
          { label: "Paused", value: counts.paused, icon: Pause, tone: "text-amber-300" },
          { label: "Completed", value: counts.completed, icon: CheckCircle2, tone: "text-sky-300" },
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

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2 bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-3.5 border-b border-border">
            <h2 className="text-sm font-semibold text-foreground">Campaigns</h2>
          </div>
          {isLoading ? (
            <div className="p-4 space-y-3">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
          ) : !campaigns?.length ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              <Radio size={32} className="mx-auto mb-3 opacity-25" />
              No campaigns yet
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border bg-muted/30">
                  <th className="px-5 py-3 text-left font-medium">Name</th>
                  <th className="px-3 py-3 text-left font-medium">Status</th>
                  <th className="px-3 py-3 text-left font-medium">Attempted</th>
                  <th className="px-3 py-3 text-left font-medium">Connected</th>
                  <th className="px-3 py-3 text-left font-medium">Failed</th>
                  <th className="px-3 py-3 text-left font-medium">Started</th>
                  <th className="px-3 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((campaign) => (
                  <tr
                    key={campaign.campaign_id}
                    className={`border-b border-border last:border-0 cursor-pointer hover:bg-secondary/30 ${selected?.campaign_id === campaign.campaign_id ? "bg-secondary/20" : ""}`}
                    onClick={() => setSelectedId(campaign.campaign_id)}
                  >
                    <td className="px-5 py-3">
                      <div className="font-medium text-foreground">{campaign.name}</div>
                      <div className="text-xs text-muted-foreground font-mono mt-0.5">{campaign.campaign_id}</div>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${statusTone(campaign.status)}`}>
                        {campaign.status}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs font-mono text-muted-foreground">{campaign.calls_attempted}</td>
                    <td className="px-3 py-3 text-xs font-mono text-muted-foreground">{campaign.calls_connected}</td>
                    <td className="px-3 py-3 text-xs font-mono text-muted-foreground">{campaign.calls_failed}</td>
                    <td className="px-3 py-3 text-xs text-muted-foreground">{fmtTime(campaign.started_at)}</td>
                    <td className="px-3 py-3">
                      <div className="flex justify-end gap-1">
                        {(campaign.status === "draft" || campaign.status === "paused") && (
                          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); actionMutation.mutate({ campaignId: campaign.campaign_id, action: "start" }); }}>
                            <Play size={12} />
                          </Button>
                        )}
                        {campaign.status === "active" && (
                          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); actionMutation.mutate({ campaignId: campaign.campaign_id, action: "pause" }); }}>
                            <Pause size={12} />
                          </Button>
                        )}
                        {(campaign.status === "active" || campaign.status === "paused") && (
                          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); actionMutation.mutate({ campaignId: campaign.campaign_id, action: "complete" }); }}>
                            <CheckCircle2 size={12} />
                          </Button>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={(e) => { e.stopPropagation(); actionMutation.mutate({ campaignId: campaign.campaign_id, action: "delete" }); }}
                          disabled={campaign.status === "active"}
                        >
                          <Trash2 size={12} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-3.5 border-b border-border">
            <h2 className="text-sm font-semibold text-foreground">Campaign Detail</h2>
          </div>
          {!selected ? (
            <div className="px-5 py-10 text-sm text-muted-foreground">Select a campaign to inspect it.</div>
          ) : (
            <div className="divide-y divide-border">
              <div className="px-5 py-4">
                <div className="text-base font-semibold text-foreground">{selected.name}</div>
                <div className="mt-1 text-xs text-muted-foreground font-mono">{selected.campaign_id}</div>
              </div>
              <div className="px-5 py-3">
                <div className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Description</div>
                <div className="text-sm text-foreground whitespace-pre-wrap">{selected.description || "—"}</div>
              </div>
              <div className="px-5 py-3">
                <div className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Caller ID</div>
                <div className="text-sm font-mono text-foreground">{selected.caller_id || "—"}</div>
              </div>
              <div className="px-5 py-3">
                <div className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Script</div>
                <div className="text-sm text-foreground whitespace-pre-wrap">{selected.script || "—"}</div>
              </div>
              <div className="px-5 py-3">
                <div className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Targets</div>
                <div className="space-y-1">
                  {selected.target_list.length ? selected.target_list.map((target) => (
                    <div key={target} className="text-sm font-mono text-foreground">{target}</div>
                  )) : <div className="text-sm text-muted-foreground">No targets</div>}
                </div>
              </div>
              <div className="px-5 py-3 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Started</div>
                  <div className="text-foreground">{fmtTime(selected.started_at)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Completed</div>
                  <div className="text-foreground">{fmtTime(selected.completed_at)}</div>
                </div>
              </div>
              <div className="px-5 py-3 flex items-center gap-2">
                <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${statusTone(selected.status)}`}>{selected.status}</span>
                {selected.status === "archived" && <Archive size={13} className="text-muted-foreground" />}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
