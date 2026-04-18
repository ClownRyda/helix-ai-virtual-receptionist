import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Voicemail, PhoneOff, Clock, CheckCircle2, Circle } from "lucide-react";
import { fetchJSON } from "@/lib/queryClient";
import { Skeleton } from "@/components/ui/skeleton";

interface VoicemailMessage {
  id: number;
  call_id: string;
  caller_id: string;
  recorded_at: string | null;
  duration_sec: number | null;
  transcript: string | null;
  status: "new" | "read" | "archived";
  audio_path: string | null;
}

function fmt(s: number | null) {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function fmtTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function StatusBadge({ status }: { status: string }) {
  if (status === "new")
    return (
      <span className="flex items-center gap-1 text-xs font-semibold text-cyan-400">
        <Circle size={9} className="fill-cyan-400" /> New
      </span>
    );
  if (status === "read")
    return (
      <span className="flex items-center gap-1 text-xs text-muted-foreground">
        <CheckCircle2 size={11} /> Read
      </span>
    );
  return (
    <span className="text-xs text-muted-foreground/50">Archived</span>
  );
}

export default function Voicemails() {
  const qc = useQueryClient();

  const { data: vms, isLoading } = useQuery<VoicemailMessage[]>({
    queryKey: ["/api/voicemails"],
    queryFn: () => fetchJSON("/api/voicemails"),
    refetchInterval: 20_000,
  });

  const markRead = useMutation({
    mutationFn: (id: number) =>
      fetch(`/api/voicemails/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "read" }),
      }).then((r) => r.json()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/voicemails"] }),
  });

  const markArchived = useMutation({
    mutationFn: (id: number) =>
      fetch(`/api/voicemails/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "archived" }),
      }).then((r) => r.json()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/voicemails"] }),
  });

  const newCount = vms?.filter((v) => v.status === "new").length ?? 0;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
            <Voicemail size={20} className="text-primary" />
            Voicemail Inbox
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {newCount > 0 ? `${newCount} new message${newCount > 1 ? "s" : ""}` : "No new messages"}
          </p>
        </div>
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-4 space-y-3">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : !vms?.length ? (
          <div className="py-16 text-center text-muted-foreground text-sm">
            <PhoneOff size={32} className="mx-auto mb-3 opacity-25" />
            No voicemails yet
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wide border-b border-border bg-secondary/30">
                <th className="px-5 py-3 text-left font-medium">Status</th>
                <th className="px-3 py-3 text-left font-medium">Caller</th>
                <th className="px-3 py-3 text-left font-medium">Received</th>
                <th className="px-3 py-3 text-left font-medium">
                  <span className="flex items-center gap-1"><Clock size={11} /> Duration</span>
                </th>
                <th className="px-3 py-3 text-left font-medium">Transcript</th>
                <th className="px-3 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {vms.map((vm) => (
                <tr
                  key={vm.id}
                  className={`border-b border-border last:border-0 transition-colors ${
                    vm.status === "new" ? "bg-primary/5" : ""
                  }`}
                >
                  <td className="px-5 py-3">
                    <StatusBadge status={vm.status} />
                  </td>
                  <td className="px-3 py-3 font-mono text-xs text-foreground">{vm.caller_id}</td>
                  <td className="px-3 py-3 text-xs text-muted-foreground">{fmtTime(vm.recorded_at)}</td>
                  <td className="px-3 py-3 text-xs text-muted-foreground font-mono">{fmt(vm.duration_sec)}</td>
                  <td className="px-3 py-3 text-xs text-muted-foreground max-w-xs">
                    {vm.transcript ? (
                      <span className="line-clamp-2">{vm.transcript}</span>
                    ) : (
                      <span className="italic opacity-50">No transcript</span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <div className="flex items-center gap-2 justify-end">
                      {vm.status === "new" && (
                        <button
                          onClick={() => markRead.mutate(vm.id)}
                          className="text-xs text-primary hover:underline disabled:opacity-40"
                          disabled={markRead.isPending}
                        >
                          Mark read
                        </button>
                      )}
                      {vm.status !== "archived" && (
                        <button
                          onClick={() => markArchived.mutate(vm.id)}
                          className="text-xs text-muted-foreground hover:text-foreground hover:underline disabled:opacity-40"
                          disabled={markArchived.isPending}
                        >
                          Archive
                        </button>
                      )}
                    </div>
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
