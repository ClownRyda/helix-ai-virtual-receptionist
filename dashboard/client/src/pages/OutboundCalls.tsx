import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { PhoneOutgoing, Radio, PhoneCall } from "lucide-react";
import { apiRequest, fetchJSON, queryClient } from "@/lib/queryClient";
import type { CallLog, OutboundTestCallResult } from "@shared/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useToast } from "@/hooks/use-toast";

function fmtDuration(seconds: number | null) {
  if (!seconds) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function fmtTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function OutboundCalls() {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<OutboundTestCallResult | null>(null);
  const [form, setForm] = useState({
    destination: "",
    caller_id: "",
    context: "helix-outbound",
  });

  const { data: calls, isLoading } = useQuery<CallLog[]>({
    queryKey: ["/api/calls", "outbound"],
    queryFn: () => fetchJSON("/api/calls?direction=outbound&limit=100"),
    refetchInterval: 15_000,
  });

  const callCount = calls?.length ?? 0;

  const testCallMutation = useMutation({
    mutationFn: async () => {
      const res = await apiRequest("POST", "/api/outbound/test-call", {
        destination: form.destination.trim(),
        caller_id: form.caller_id.trim() || undefined,
        context: form.context.trim() || "helix-outbound",
      });
      return res.json() as Promise<OutboundTestCallResult>;
    },
    onSuccess: async (payload) => {
      setResult(payload);
      await queryClient.invalidateQueries({ queryKey: ["/api/calls"] });
      setOpen(false);
      toast({ title: "Test call originated" });
    },
    onError: (error: Error) => {
      toast({ title: "Test call failed", description: error.message, variant: "destructive" });
    },
  });

  const todayCount = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return (calls ?? []).filter((call) => {
      if (!call.started_at) return false;
      return new Date(call.started_at) >= start;
    }).length;
  }, [calls]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Outbound Calls</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manual proof-of-life dialing through ARI. This page places individual test calls.
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <PhoneCall size={13} /> Test Call
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Place Outbound Test Call</DialogTitle>
            </DialogHeader>
            <div className="grid gap-3 py-2">
              <Input
                placeholder="Destination (e.g. 1001)"
                value={form.destination}
                onChange={(e) => setForm({ ...form, destination: e.target.value })}
                className="font-mono"
              />
              <Input
                placeholder="Caller ID (optional)"
                value={form.caller_id}
                onChange={(e) => setForm({ ...form, caller_id: e.target.value })}
                className="font-mono"
              />
              <Input
                placeholder="Context"
                value={form.context}
                onChange={(e) => setForm({ ...form, context: e.target.value })}
                className="font-mono"
              />
              <div className="flex justify-end">
                <Button onClick={() => testCallMutation.mutate()} disabled={!form.destination.trim() || testCallMutation.isPending}>
                  Ring Phone
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Outbound Today</span>
            <PhoneOutgoing size={13} className="text-primary" />
          </div>
          <div className="text-2xl font-bold text-foreground mono">{todayCount}</div>
        </div>
        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Logged Outbound Calls</span>
            <Radio size={13} className="text-sky-300" />
          </div>
          <div className="text-2xl font-bold text-foreground mono">{callCount}</div>
        </div>
      </div>

      {result && (
        <Alert className="border-primary/20 bg-primary/5">
          <PhoneOutgoing size={16} className="text-primary" />
          <AlertTitle>Test call started</AlertTitle>
          <AlertDescription>
            Channel <span className="font-mono">{result.channel_id}</span> created for destination{" "}
            <span className="font-mono">{result.destination}</span> in context{" "}
            <span className="font-mono">{result.context}</span>.
          </AlertDescription>
        </Alert>
      )}

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Outbound Call Log</h2>
        </div>
        {isLoading ? (
          <div className="p-4 space-y-3">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : !calls?.length ? (
          <div className="py-16 text-center text-sm text-muted-foreground">
            <PhoneOutgoing size={32} className="mx-auto mb-3 opacity-25" />
            No outbound calls yet
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border bg-muted/30">
                <th className="px-5 py-3 text-left font-medium">Timestamp</th>
                <th className="px-3 py-3 text-left font-medium">Destination</th>
                <th className="px-3 py-3 text-left font-medium">Status</th>
                <th className="px-3 py-3 text-left font-medium">Duration</th>
                <th className="px-3 py-3 text-left font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((call) => (
                <tr key={call.id} className="border-b border-border last:border-0">
                  <td className="px-5 py-3 text-xs text-muted-foreground">{fmtTime(call.started_at)}</td>
                  <td className="px-3 py-3 font-mono text-xs text-primary">{call.called_number}</td>
                  <td className="px-3 py-3 text-xs text-foreground capitalize">{call.disposition || "—"}</td>
                  <td className="px-3 py-3 text-xs text-muted-foreground font-mono">{fmtDuration(call.duration_seconds)}</td>
                  <td className="px-3 py-3 text-xs text-muted-foreground font-mono truncate max-w-[18rem]">{call.notes || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
