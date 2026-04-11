import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Plus, Trash2, Pencil, Check, X, GitMerge } from "lucide-react";
import { fetchJSON, apiRequest, queryClient } from "@/lib/queryClient";
import type { RoutingRule } from "@shared/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import { Skeleton } from "@/components/ui/skeleton";

interface EditState {
  id: number;
  keyword: string;
  extension: string;
  description: string;
  priority: number;
}

export default function Routing() {
  const { toast } = useToast();
  const [editing, setEditing] = useState<EditState | null>(null);
  const [adding, setAdding] = useState(false);
  const [newRule, setNewRule] = useState({ keyword: "", extension: "", description: "", priority: 100 });

  const { data: rules, isLoading } = useQuery<RoutingRule[]>({
    queryKey: ["/api/rules"],
    queryFn: () => fetchJSON("/api/rules"),
  });

  const updateMutation = useMutation({
    mutationFn: async (r: EditState) =>
      apiRequest("PUT", `/api/rules/${r.id}`, {
        extension: r.extension,
        description: r.description,
        priority: r.priority,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/rules"] });
      setEditing(null);
      toast({ title: "Rule updated" });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: async ({ id, active }: { id: number; active: boolean }) =>
      apiRequest("PUT", `/api/rules/${id}`, { active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["/api/rules"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => apiRequest("DELETE", `/api/rules/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/rules"] });
      toast({ title: "Rule deleted" });
    },
  });

  const createMutation = useMutation({
    mutationFn: async (r: typeof newRule) =>
      apiRequest("POST", "/api/rules", r),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/rules"] });
      setAdding(false);
      setNewRule({ keyword: "", extension: "", description: "", priority: 100 });
      toast({ title: "Rule created" });
    },
  });

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Routing Rules</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Map intent keywords to extensions. Lower priority number = matched first.
          </p>
        </div>
        <Button
          data-testid="button-add-rule"
          size="sm"
          onClick={() => setAdding(true)}
          className="gap-1.5"
        >
          <Plus size={13} /> Add Rule
        </Button>
      </div>

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {/* Header row */}
        <div className="rule-row bg-muted/40">
          <span className="text-xs text-muted-foreground uppercase tracking-wide font-medium">Keyword</span>
          <span className="text-xs text-muted-foreground uppercase tracking-wide font-medium">Ext</span>
          <span className="text-xs text-muted-foreground uppercase tracking-wide font-medium">Description</span>
          <span className="text-xs text-muted-foreground uppercase tracking-wide font-medium">Priority</span>
          <span className="text-xs text-muted-foreground uppercase tracking-wide font-medium">Active</span>
        </div>

        {isLoading ? (
          <div className="p-4 space-y-3">
            {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : !rules?.length ? (
          <div className="py-12 text-center text-muted-foreground text-sm">
            <GitMerge size={32} className="mx-auto mb-3 opacity-25" />
            No routing rules
          </div>
        ) : (
          rules.map((rule) => {
            const isEditing = editing?.id === rule.id;
            return (
              <div key={rule.id} className={`rule-row ${!rule.active ? "opacity-50" : ""}`}>
                {isEditing ? (
                  <>
                    <Input
                      value={editing.keyword}
                      disabled
                      className="h-7 text-xs bg-secondary border-border mono"
                    />
                    <Input
                      data-testid={`input-extension-${rule.id}`}
                      value={editing.extension}
                      onChange={(e) => setEditing({ ...editing, extension: e.target.value })}
                      className="h-7 text-xs bg-secondary border-border mono"
                      placeholder="1001"
                    />
                    <Input
                      data-testid={`input-description-${rule.id}`}
                      value={editing.description}
                      onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                      className="h-7 text-xs bg-secondary border-border"
                      placeholder="Description"
                    />
                    <Input
                      data-testid={`input-priority-${rule.id}`}
                      type="number"
                      value={editing.priority}
                      onChange={(e) => setEditing({ ...editing, priority: Number(e.target.value) })}
                      className="h-7 text-xs bg-secondary border-border mono w-16"
                    />
                    <div className="flex gap-1">
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 text-primary"
                        onClick={() => updateMutation.mutate(editing)}
                      >
                        <Check size={12} />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 text-muted-foreground"
                        onClick={() => setEditing(null)}
                      >
                        <X size={12} />
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <span className="text-sm mono font-medium text-foreground">{rule.keyword}</span>
                    <span className="text-sm mono text-primary font-semibold">{rule.extension}</span>
                    <span className="text-xs text-muted-foreground">{rule.description || "—"}</span>
                    <span className="text-xs mono text-muted-foreground">{rule.priority}</span>
                    <div className="flex items-center gap-2">
                      <Switch
                        data-testid={`toggle-rule-${rule.id}`}
                        checked={rule.active}
                        onCheckedChange={(v) => toggleMutation.mutate({ id: rule.id, active: v })}
                        className="scale-75"
                      />
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 text-muted-foreground hover:text-foreground"
                        onClick={() => setEditing({
                          id: rule.id,
                          keyword: rule.keyword,
                          extension: rule.extension,
                          description: rule.description || "",
                          priority: rule.priority,
                        })}
                      >
                        <Pencil size={11} />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 text-muted-foreground hover:text-destructive"
                        onClick={() => deleteMutation.mutate(rule.id)}
                      >
                        <Trash2 size={11} />
                      </Button>
                    </div>
                  </>
                )}
              </div>
            );
          })
        )}

        {/* Add new rule form */}
        {adding && (
          <div className="rule-row border-t border-primary/30 bg-primary/5">
            <Input
              data-testid="input-new-keyword"
              placeholder="keyword"
              value={newRule.keyword}
              onChange={(e) => setNewRule({ ...newRule, keyword: e.target.value })}
              className="h-7 text-xs bg-secondary border-border mono"
            />
            <Input
              data-testid="input-new-extension"
              placeholder="1001"
              value={newRule.extension}
              onChange={(e) => setNewRule({ ...newRule, extension: e.target.value })}
              className="h-7 text-xs bg-secondary border-border mono"
            />
            <Input
              data-testid="input-new-description"
              placeholder="Description"
              value={newRule.description}
              onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
              className="h-7 text-xs bg-secondary border-border"
            />
            <Input
              data-testid="input-new-priority"
              type="number"
              value={newRule.priority}
              onChange={(e) => setNewRule({ ...newRule, priority: Number(e.target.value) })}
              className="h-7 text-xs bg-secondary border-border mono w-16"
            />
            <div className="flex gap-1">
              <Button
                data-testid="button-save-rule"
                size="icon"
                variant="ghost"
                className="h-6 w-6 text-primary"
                onClick={() => createMutation.mutate(newRule)}
                disabled={!newRule.keyword || !newRule.extension}
              >
                <Check size={12} />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6 text-muted-foreground"
                onClick={() => setAdding(false)}
              >
                <X size={12} />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="text-xs text-muted-foreground space-y-1 pt-1">
        <p>When a caller says "I need <strong className="text-foreground">sales</strong>", the agent matches that keyword and transfers to the mapped extension.</p>
        <p>Keywords are matched against Ollama's intent detection output. Add any words callers might say.</p>
      </div>
    </div>
  );
}
