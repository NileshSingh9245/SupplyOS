"use client";

export default function AuditPage() {
  return (
    <div className="page-shell">
      <header className="page-header">
        <p className="data-label">Compliance</p>
        <h1 className="page-title">Audit Log</h1>
        <p className="text-text-secondary text-sm mt-1">
          Every mutating action is recorded. Log rows are append-only.
        </p>
      </header>
      <div className="page-body">
        <div className="pane p-12 text-center">
          <p className="text-text-secondary">
            Audit log viewer coming next milestone. Every action is being
            recorded now — visible via{" "}
            <code className="text-volt">audit_logs</code> table.
          </p>
        </div>
      </div>
    </div>
  );
}
