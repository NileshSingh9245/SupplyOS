"use client";

export default function AuditPage() {
  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5">
        <p className="data-label">Compliance</p>
        <h1 className="font-display text-3xl font-black tracking-tightest">Audit Log</h1>
        <p className="text-text-secondary text-sm mt-1">
          Every mutating action is recorded. Log rows are append-only.
        </p>
      </header>
      <div className="flex-1 overflow-auto p-8">
        <div className="pane p-12 text-center">
          <p className="text-text-secondary">Audit log viewer coming next milestone. Every action is being recorded now — visible via <code className="text-volt">audit_logs</code> table.</p>
        </div>
      </div>
    </div>
  );
}
