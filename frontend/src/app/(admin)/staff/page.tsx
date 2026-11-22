"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/modal";
import { useAuth } from "@/lib/auth";
import {
  accountEmailSchema, accountPasswordSchema, createStaff, patchStaff, revokeStaffSessions,
  staffDetailsSchema, staffQuery, staffRequestError, staffRoleLabels, staffRoles, staffScope,
  type StaffMember, type StaffPatch, type StaffRole, type StaffScope,
} from "@/lib/staff";

type StaffAction = { kind: "create" } | { kind: "edit"; member: StaffMember } |
  { kind: "deactivate" | "reactivate" | "revoke"; member: StaffMember };

export default function StaffPage() {
  const user = useAuth((state) => state.user);
  const sessionVersion = useAuth((state) => state.sessionVersion);
  const scope = staffScope(user, sessionVersion);
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [action, setAction] = useState<StaffAction | null>(null);
  const query = useQuery(staffQuery(scope, page));
  if (!scope) return <p role="alert" className="p-6">Only the signed-in owner may manage staff.</p>;
  const close = () => setAction(null);
  const done = () => { void client.invalidateQueries({ queryKey: ["staff"] }); close(); };

  return <div className="page-shell" data-testid="staff-page">
    <header className="page-header">
      <div><p className="data-label">Access directory / Owner only</p><h1 className="page-title">Staff</h1></div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost inline-flex items-center gap-2" disabled={query.isFetching}
          onClick={() => void query.refetch()} data-testid="staff-refresh"><RefreshCw size={14} aria-hidden="true" /> Refresh</button>
        <button type="button" className="btn-volt inline-flex items-center gap-2" disabled={query.isFetching || query.isError || !query.data} onClick={() => setAction({ kind: "create" })}
          data-testid="staff-new"><Plus size={14} aria-hidden="true" /> Add staff</button>
      </div>
    </header>
    <div className="page-body space-y-4">
      <p className="text-sm text-text-secondary">Create individual staff accounts with holder-chosen private passwords. This does not send invitations, verify email, or sign anyone in. Warehouse roles are not warehouse assignments.</p>
      {query.isFetching && <p role="status" data-testid="staff-loading">Loading staff...</p>}
      {query.isError ? <div className="pane p-4 space-y-3" data-testid="staff-error">
        <p role="alert">{query.error.message}</p>
        <button type="button" className="btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>Retry staff list</button>
      </div> : query.data ? <>
        <StaffTable members={query.data.items} busy={query.isFetching} onAction={setAction} />
        <nav aria-label="Staff pages" className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-ghost" disabled={page === 1 || query.isFetching}
            onClick={() => setPage(page - 1)} data-testid="staff-previous">Previous</button>
          <p role="status" className="text-sm" data-testid="staff-pagination">Page {query.data.page} / {query.data.total} staff accounts</p>
          <button type="button" className="btn-ghost" disabled={query.isFetching || query.data.page * query.data.page_size >= query.data.total}
            onClick={() => setPage(page + 1)} data-testid="staff-next">Next</button>
        </nav>
      </> : null}
    </div>
    {action && (action.kind === "create" || action.kind === "edit" ?
      <StaffForm key={`${scope.tenantId}:${scope.userId}:${scope.sessionVersion}:${action.kind}`}
        scope={scope} member={action.kind === "edit" ? action.member : undefined} onClose={close} onDone={done} /> :
      <StaffConfirmation key={`${scope.tenantId}:${scope.userId}:${scope.sessionVersion}:${action.kind}:${action.member.id}`}
        scope={scope} member={action.member} kind={action.kind} onClose={close} onDone={done} />)}
  </div>;
}

function StaffTable({ members, busy, onAction }: {
  members: StaffMember[]; busy: boolean; onAction: (action: StaffAction) => void;
}) {
  if (!members.length) return <p role="status" className="pane p-5" data-testid="staff-empty">No staff accounts on this page.</p>;
  return <div className="pane overflow-x-auto mobile-cards">
    <table className="grid" data-testid="staff-table">
      <caption className="sr-only">Staff accounts, roles and account access actions</caption>
      <thead><tr>{["Name", "Email", "Phone", "Role", "Access", "Created", "Actions"].map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
      <tbody>{members.map((member) => <tr key={member.id} data-testid={`staff-row-${member.id}`}>
        <td data-label="Name"><span className="min-w-0 break-words">{member.full_name}</span></td>
        <td data-label="Email"><span className="break-all">{member.email}</span></td>
        <td data-label="Phone"><span className="min-w-0 break-all">{member.phone || "Not provided"}</span></td>
        <td data-label="Role">{staffRoleLabels[member.role]}</td>
        <td data-label="Access"><span className={`chip ${member.is_active ? "chip-info" : "chip-muted"}`}>{member.is_active ? "Active" : "Inactive"}</span></td>
        <td data-label="Created"><time dateTime={member.created_at}>{new Date(member.created_at).toLocaleDateString()}</time></td>
        <td data-label="Actions"><div className="flex flex-wrap justify-end gap-2">
          <button type="button" className="btn-ghost text-xs" disabled={busy} aria-label={`Edit ${member.full_name}`}
            data-testid={`staff-edit-${member.id}`} onClick={() => onAction({ kind: "edit", member })}>Edit</button>
          <button type="button" className="btn-ghost text-xs" disabled={busy} aria-label={`${member.is_active ? "Deactivate" : "Reactivate"} ${member.full_name}`}
            data-testid={`staff-activity-${member.id}`} onClick={() => onAction({ kind: member.is_active ? "deactivate" : "reactivate", member })}>
            {member.is_active ? "Deactivate" : "Reactivate"}</button>
          <button type="button" className="btn-ghost text-xs" disabled={busy} aria-label={`Revoke sessions for ${member.full_name}`}
            data-testid={`staff-revoke-${member.id}`} onClick={() => onAction({ kind: "revoke", member })}>Revoke sessions</button>
        </div></td>
      </tr>)}</tbody>
    </table>
  </div>;
}

interface StaffFormFields { email: string; full_name: string; phone: string; role: StaffRole; password: string; confirmed: boolean }

function StaffForm({ scope, member, onClose, onDone }: {
  scope: StaffScope; member?: StaffMember; onClose: () => void; onDone: () => void;
}) {
  const schema = staffDetailsSchema.extend({
    email: member ? z.string() : accountEmailSchema, password: member ? z.string() : accountPasswordSchema,
    confirmed: z.boolean().refine(Boolean, "Confirm the account changes before submitting."),
  });
  const { register, control, handleSubmit, resetField, setValue, formState: { isValid, errors } } = useForm<StaffFormFields>({
    resolver: zodResolver(schema), mode: "onChange",
    defaultValues: { email: member?.email || "", full_name: member?.full_name || "", phone: member?.phone || "",
      role: member?.role, password: "", confirmed: false },
  });
  const values = useWatch({ control });
  const changed = !member || values.full_name?.trim() !== member.full_name ||
    (values.phone?.trim() || null) !== member.phone || values.role !== member.role;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); };
  }, []);
  async function submit(form: StaffFormFields) {
    if (!mounted.current || pending.current || !changed) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setError(null);
    resetField("password", { defaultValue: "" });
    setValue("confirmed", false);
    try {
      if (!member) await createStaff(scope, { email: form.email, full_name: form.full_name, phone: form.phone, role: form.role, password: form.password }, controller.signal);
      else {
        const patch: StaffPatch = {};
        if (form.full_name !== member.full_name) patch.full_name = form.full_name;
        if ((form.phone || null) !== member.phone) patch.phone = form.phone || null;
        if (form.role !== member.role) patch.role = form.role;
        await patchStaff(scope, member.id, patch, controller.signal);
      }
      if (!mounted.current) return;
      toast.success(member ? "Staff account changes saved." : "Staff account created. Email is unverified; no invitation was sent.");
      onDone();
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted) setError(staffRequestError(failure));
    } finally {
      if (pending.current === controller) pending.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  return <Modal open busy={busy} onClose={onClose} labelledBy="staff-form-title" testId="staff-modal">
    <h2 id="staff-form-title" className="font-display text-2xl font-bold mb-3">{member ? "Edit staff account" : "New staff account"}</h2>
    <p className="text-sm text-text-secondary mb-4">{member ? "Email and password cannot be changed here. A role change revokes sessions and reset links." : "The account holder must choose and privately enter their final password. No generated or temporary credentials, invitation, email verification, or automatic login."}</p>
    <form noValidate onSubmit={(event) => void handleSubmit(submit)(event)} aria-busy={busy} onChange={(event) => {
      setError(null);
      if ((event.target as HTMLInputElement).name !== "confirmed") setValue("confirmed", false, { shouldValidate: true });
    }}>
      <fieldset disabled={busy} className="space-y-4 min-w-0">
        <div><label htmlFor="staff-name" className="data-label">Full name *</label>
          <input id="staff-name" className="input mt-1" maxLength={200} data-testid="staff-name" aria-invalid={!!errors.full_name} {...register("full_name")} />
          {errors.full_name && <p role="alert" className="text-sm">{errors.full_name.message}</p>}</div>
        <div><label htmlFor="staff-email" className="data-label">Email {member ? "(read-only)" : "*"}</label>
          <input id="staff-email" className="input mt-1" type="email" autoComplete="off" maxLength={200} readOnly={!!member}
            data-testid="staff-email" aria-invalid={!!errors.email} {...register("email")} />
          {errors.email && <p role="alert" className="text-sm">{errors.email.message}</p>}</div>
        <div><label htmlFor="staff-phone" className="data-label">Phone (optional)</label>
          <input id="staff-phone" className="input mt-1" type="tel" maxLength={30} data-testid="staff-phone" aria-invalid={!!errors.phone} {...register("phone")} />
          {errors.phone && <p role="alert" className="text-sm">Use no more than 30 characters.</p>}</div>
        <div><label htmlFor="staff-role" className="data-label">Role *</label>
          <select id="staff-role" className="input mt-1" data-testid="staff-role" aria-invalid={!!errors.role} {...register("role")}>
            <option value="">Choose a staff role...</option>{staffRoles.map((role) => <option key={role} value={role}>{staffRoleLabels[role]}</option>)}
          </select></div>
        {!member && <div><label htmlFor="staff-password" className="data-label">Account holder&apos;s final private password *</label>
          <input id="staff-password" className="input mt-1" type="password" autoComplete="new-password" maxLength={72}
            data-testid="staff-password" aria-describedby="staff-password-help" aria-invalid={!!errors.password} {...register("password")} />
          <p id="staff-password-help" className="text-xs text-text-secondary mt-2">At least 12 characters and at most 72 UTF-8 bytes. Cleared on submission, including failures.</p>
          {errors.password && <p role="alert" className="text-sm">{errors.password.message}</p>}</div>}
        <label className="flex items-start gap-3 text-sm" htmlFor="staff-confirmed">
          <input id="staff-confirmed" className="mt-1 h-4 w-4 shrink-0" type="checkbox" data-testid="staff-confirmed" {...register("confirmed")} />
          <span>{member ? "I confirm these profile and role changes." : "The account holder chose and privately entered this final password. I confirm creation of a new staff account."}</span>
        </label>
      </fieldset>
      {error && <p role="alert" className="text-sm text-status-alert mt-4" data-testid="staff-form-error">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2 mt-5">
        <button type="button" className="btn-ghost" disabled={busy} onClick={onClose} data-testid="staff-cancel">Cancel</button>
        <button type="submit" className="btn-volt" disabled={busy || !isValid || !changed} data-testid="staff-submit">{busy ? "Saving..." : member ? "Save confirmed changes" : "Create staff account"}</button>
      </div>
    </form>
  </Modal>;
}

const confirmationCopy = {
  deactivate: { title: "Deactivate staff account", action: "Confirm deactivation", detail: "This blocks sign-in and revokes existing sessions and reset links. Existing delivery and warehouse assignments are not deleted or reassigned here." },
  reactivate: { title: "Reactivate staff account", action: "Confirm reactivation", detail: "The holder may sign in with their existing password. Previously revoked sessions are not restored. No invitation or email verification is performed." },
  revoke: { title: "Revoke staff sessions", action: "Confirm session revocation", detail: "This invalidates existing sessions and reset links without changing the account's active status. A session list is not available here." },
};

function StaffConfirmation({ scope, member, kind, onClose, onDone }: {
  scope: StaffScope; member: StaffMember; kind: keyof typeof confirmationCopy; onClose: () => void; onDone: () => void;
}) {
  const copy = confirmationCopy[kind];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); };
  }, []);
  async function confirm() {
    if (!mounted.current || pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(null);
    try {
      if (kind === "revoke") await revokeStaffSessions(scope, member.id, controller.signal);
      else await patchStaff(scope, member.id, { is_active: kind === "reactivate" }, controller.signal);
      if (!mounted.current) return;
      toast.success(kind === "revoke" ? "Staff sessions revoked." : kind === "deactivate" ? "Staff account deactivated." : "Staff account reactivated. Previous sessions remain revoked.");
      onDone();
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted) setError(staffRequestError(failure));
    } finally {
      if (pending.current === controller) pending.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  return <Modal open busy={busy} onClose={onClose} labelledBy="staff-confirm-title" testId="staff-confirm-modal">
    <h2 id="staff-confirm-title" className="font-display text-2xl font-bold mb-3">{copy.title}</h2>
    <p className="text-sm break-words mb-3">Account: {member.full_name}</p>
    <p className="text-sm text-text-secondary">{copy.detail}</p>
    {error && <p role="alert" className="text-sm text-status-alert mt-4">{error}</p>}
    <div className="flex flex-wrap justify-end gap-2 mt-5">
      <button type="button" className="btn-ghost" disabled={busy} onClick={onClose} data-testid="staff-confirm-cancel">Cancel</button>
      <button type="button" className="btn-volt" disabled={busy} onClick={() => void confirm()} data-testid="staff-confirm">{busy ? "Applying..." : copy.action}</button>
    </div>
  </Modal>;
}
