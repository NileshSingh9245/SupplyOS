"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Sparkles, Play, X } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

interface Alert {
  id: string;
  category: string;
  severity: string;
  title: string;
  message: string;
  action_hint: string | null;
  created_at: string;
  is_dismissed: boolean;
  meta: Record<string, unknown> | null;
}

interface AICapabilities {
  free_only_mode: boolean;
  can_request_summary: boolean;
  summary_status: "configured" | "unavailable" | "held_free_only";
}

const SEVERITY_CHIP: Record<string, string> = {
  critical: "chip-alert",
  warning: "chip-warning",
  info: "chip-info",
};

export default function AISupervisorPage() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const { data: capabilities } = useQuery({
    queryKey: ["ai-capabilities"],
    queryFn: async () => (await api.get<AICapabilities>("/ai/capabilities")).data,
  });
  const canRequestSummary = capabilities?.can_request_summary === true;
  const { data: alerts } = useQuery({
    queryKey: ["alerts-full"],
    queryFn: async () =>
      (await api.get<Alert[]>("/ai/alerts?limit=200&include_dismissed=false"))
        .data,
  });

  async function analyze(withAI: boolean) {
    if (busy || (withAI && !canRequestSummary)) return;
    setBusy(true);
    try {
      const { data } = await api.post<{
        counts: Record<string, number>;
        summary_status?: "not_requested" | "queued" | "unavailable" | "held_free_only";
      }>(
        `/ai/analyze?include_summary=${withAI}`,
      );
      const total = Object.values(data.counts).reduce((a, b) => a + b, 0);
      toast.success(
        `Analysis complete. ${total} rule alerts refreshed.${data.summary_status === "queued" ? " Generative summary queued." : ""}`,
      );
      if (withAI && data.summary_status !== "queued") {
        toast.info("Generative summaries are on hold; rule checks completed.");
        qc.invalidateQueries({ queryKey: ["ai-capabilities"] });
      }
      setTimeout(
        () => qc.invalidateQueries({ queryKey: ["alerts-full"] }),
        data.summary_status === "queued" ? 3000 : 500,
      );
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function dismiss(id: string) {
    try {
      await api.post(`/ai/alerts/${id}/dismiss`);
      qc.invalidateQueries({ queryKey: ["alerts-full"] });
    } catch (e) {
      toast.error(apiError(e));
    }
  }

  const grouped = (alerts ?? []).reduce<Record<string, Alert[]>>((acc, a) => {
    (acc[a.category] ??= []).push(a);
    return acc;
  }, {});

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="data-label">AI</p>
          <h1 className="page-title flex items-center gap-2">
            <Sparkles className="text-volt" size={28} /> AI Supervisor
          </h1>
          <p className="text-text-secondary text-sm mt-1">
            Rule-based business checks remain available without a paid provider.
            Generative summaries require an approved configuration and quality validation.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap w-full sm:w-auto">
          <button
            className="btn-ghost inline-flex items-center gap-2"
            data-testid="ai-run-rules"
            onClick={() => analyze(false)}
            disabled={busy}
          >
            <Play size={14} /> Run rule checks
          </button>
          <button
            className="btn-volt inline-flex items-center gap-2"
            data-testid="ai-run-summary"
            onClick={() => analyze(true)}
            disabled={busy || !canRequestSummary}
            aria-describedby="ai-summary-status"
          >
            <Sparkles size={14} /> Generate summary
          </button>
        </div>
      </header>

      <div className="page-body space-y-6">
        <p id="ai-summary-status" role="status" className="text-text-secondary text-sm" data-testid="ai-summary-status">
          {capabilities?.summary_status === "held_free_only"
            ? "On hold: paid generative summaries are disabled in free mode. No lower-quality replacement is enabled."
            : canRequestSummary ? "Generative provider configured; live availability depends on the approved provider."
              : "Generative summaries are unavailable until their configuration is confirmed."}
        </p>
        {Object.entries(grouped).length === 0 && (
          <div className="pane p-12 text-center">
            <p className="text-text-secondary">
              No active alerts. All systems calm — run the checks above to
              refresh.
            </p>
          </div>
        )}
        {Object.entries(grouped).map(([cat, list]) => (
          <div key={cat}>
            <p className="data-label mb-3">{cat}</p>
            <div className="grid md:grid-cols-2 gap-4">
              {list.map((a) => (
                <div
                  key={a.id}
                  className={`pane p-5 relative ${a.severity === "critical" ? "border-status-alert" : a.severity === "warning" ? "border-status-warning" : ""}`}
                  data-testid={`ai-alert-${a.id}`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className={`chip ${SEVERITY_CHIP[a.severity] || "chip-muted"}`}
                    >
                      {a.severity}
                    </span>
                    <span className="data-label">
                      {formatDateTime(a.created_at)}
                    </span>
                    <button
                      className="ml-auto text-text-tertiary hover:text-text-primary"
                      data-testid={`ai-dismiss-${a.id}`}
                      onClick={() => dismiss(a.id)}
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <h3 className="font-display text-lg font-bold">{a.title}</h3>
                  <p className="text-text-secondary text-sm mt-2 whitespace-pre-wrap">
                    {a.message}
                  </p>
                  {a.action_hint && (
                    <p className="text-volt text-sm mt-3 font-medium">
                      → {a.action_hint}
                    </p>
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
