"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Sparkles, Play, X } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

interface Alert {
  id: string; category: string; severity: string; title: string; message: string;
  action_hint: string | null; created_at: string; is_dismissed: boolean;
  meta: Record<string, unknown> | null;
}

const SEVERITY_CHIP: Record<string, string> = {
  critical: "chip-alert", warning: "chip-warning", info: "chip-info",
};

export default function AISupervisorPage() {
  const qc = useQueryClient();
  const { data: alerts } = useQuery({
    queryKey: ["alerts-full"],
    queryFn: async () => (await api.get<Alert[]>("/ai/alerts?limit=200&include_dismissed=false")).data,
  });

  async function analyze(withAI: boolean) {
    try {
      const { data } = await api.post<{ counts: Record<string, number> }>(`/ai/analyze?include_summary=${withAI}`);
      const total = Object.values(data.counts).reduce((a, b) => a + b, 0);
      toast.success(`Analysis complete. ${total} rule alerts refreshed.${withAI ? " Claude summary queued." : ""}`);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["alerts-full"] }), withAI ? 3000 : 500);
    } catch (e) { toast.error(apiError(e)); }
  }

  async function dismiss(id: string) {
    try {
      await api.post(`/ai/alerts/${id}/dismiss`);
      qc.invalidateQueries({ queryKey: ["alerts-full"] });
    } catch (e) { toast.error(apiError(e)); }
  }

  const grouped = (alerts ?? []).reduce<Record<string, Alert[]>>((acc, a) => {
    (acc[a.category] ??= []).push(a); return acc;
  }, {});

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="data-label">AI</p>
          <h1 className="font-display text-3xl font-black tracking-tightest flex items-center gap-2">
            <Sparkles className="text-volt" size={28} /> AI Supervisor
          </h1>
          <p className="text-text-secondary text-sm mt-1">
            Rule-based alerts run instantly. Claude Sonnet 4.5 generates executive summaries on demand.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost inline-flex items-center gap-2" data-testid="ai-run-rules" onClick={() => analyze(false)}>
            <Play size={14} /> Run rule checks
          </button>
          <button className="btn-volt inline-flex items-center gap-2" data-testid="ai-run-summary" onClick={() => analyze(true)}>
            <Sparkles size={14} /> Generate Claude summary
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-8 space-y-6">
        {Object.entries(grouped).length === 0 && (
          <div className="pane p-12 text-center">
            <p className="text-text-secondary">No active alerts. All systems calm — run the checks above to refresh.</p>
          </div>
        )}
        {Object.entries(grouped).map(([cat, list]) => (
          <div key={cat}>
            <p className="data-label mb-3">{cat}</p>
            <div className="grid md:grid-cols-2 gap-4">
              {list.map((a) => (
                <div key={a.id} className={`pane p-5 relative ${a.severity === "critical" ? "border-status-alert" : a.severity === "warning" ? "border-status-warning" : ""}`} data-testid={`ai-alert-${a.id}`}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`chip ${SEVERITY_CHIP[a.severity] || "chip-muted"}`}>{a.severity}</span>
                    <span className="data-label">{formatDateTime(a.created_at)}</span>
                    <button className="ml-auto text-text-tertiary hover:text-text-primary"
                      data-testid={`ai-dismiss-${a.id}`}
                      onClick={() => dismiss(a.id)}>
                      <X size={16} />
                    </button>
                  </div>
                  <h3 className="font-display text-lg font-bold">{a.title}</h3>
                  <p className="text-text-secondary text-sm mt-2 whitespace-pre-wrap">{a.message}</p>
                  {a.action_hint && (
                    <p className="text-volt text-sm mt-3 font-medium">→ {a.action_hint}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
