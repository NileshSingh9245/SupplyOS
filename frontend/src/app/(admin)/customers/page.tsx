"use client";

import { useDeferredValue, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import axios from "axios";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth, type AuthUser } from "@/lib/auth";
import { Modal } from "@/components/modal";
import { accountEmailSchema, accountPasswordSchema } from "@/lib/staff";
import { formatINR } from "@/lib/utils";
import { moneyInput } from "@/lib/finance";

const customerDirectorySchema = z.object({
  items: z.array(z.object({
    id: z.string().min(1), code: z.string(), name: z.string(), customer_type: z.enum(["cash", "credit"]), is_active: z.boolean(),
    business_name: z.string().nullable().optional(), phone: z.string().nullable().optional(),
    gstin: z.string().nullable().optional(), price_tier: z.string().nullable().optional(),
    credit_limit: z.string(), outstanding: z.string(), credit_held: z.string(), cash_funded_pending: z.string(),
    credit_exposure: z.string(), available_credit: z.string(), advance_balance: z.string(),
  })),
  total: z.number().int().nonnegative().optional(), page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().optional(),
});

function customerScope(user: AuthUser | null | undefined, version: number): string | null {
  return user?.is_active && ["super_admin", "accountant"].includes(user.role)
    ? `${user.tenant_id}:${user.id}:${user.role}:${version}` : null;
}

function requireCustomerSession(scope: string) {
  const state = useAuth.getState();
  if (customerScope(state.user, state.sessionVersion) !== scope) throw new axios.CanceledError("Customer access changed.");
}

function customerRequestError(error: unknown, account = false): string {
  const status = axios.isAxiosError(error) ? error.response?.status : undefined;
  if (status === 401 || status === 403) return "Only the signed-in owner or an accountant may add customers. Check your session.";
  if (status === 409) return account ? "This email is already registered. No new customer account was created or linked."
    : "This customer record conflicts with an existing record. Refresh the directory and review duplicates.";
  if (status === 400 || status === 422) return "Review the customer fields before submitting. Account passwords need at least 12 characters and at most 72 UTF-8 bytes.";
  return "The result could not be confirmed. Refresh the directory and check for a new record before retrying.";
}

export default function CustomersPage() {
  const qc = useQueryClient();
  const user = useAuth((state) => state.user);
  const sessionVersion = useAuth((state) => state.sessionVersion);
  const scope = customerScope(user, sessionVersion);
  const [q, setQ] = useState("");
  const search = useDeferredValue(q.trim());
  const [page, setPage] = useState(1);
  const [show, setShow] = useState<"record" | "account" | null>(null);

  const query = useQuery({
    queryKey: ["customers", scope, search, page], enabled: scope !== null, retry: false,
    queryFn: async ({ signal }) => {
      try {
        if (!scope) throw new axios.CanceledError("Customer access unavailable.");
        requireCustomerSession(scope);
        const params = new URLSearchParams();
        params.set("page_size", "200"); params.set("page", String(page));
        if (search) params.set("q", search);
        const { data } = await api.get<unknown>(`/customers?${params}`, { signal });
        requireCustomerSession(scope);
        const result = customerDirectorySchema.safeParse(data);
        if (!result.success || (result.data.page !== undefined && result.data.page !== page) ||
            (result.data.page_size !== undefined && result.data.page_size !== 200)) throw new Error("Invalid customer response.");
        return result.data;
      } catch (failure) {
        if (axios.isCancel(failure)) throw failure;
        throw new Error("The customer directory could not be loaded.");
      }
    },
  });
  const data = query.data;
  if (!scope) return <p role="alert" className="p-6">Only the signed-in owner or an accountant may manage customers.</p>;
  const done = () => {
    void qc.invalidateQueries({ queryKey: ["customers"] });
    void qc.invalidateQueries({ queryKey: ["customers-min"] });
    setShow(null);
  };

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="data-label">Directory</p>
          <h1 className="page-title">Customers</h1>
        </div>
        <div className="flex flex-wrap gap-2 w-full sm:w-auto sm:justify-end">
          <div className="relative w-full sm:w-auto">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary"
            />
            <input
              className="input pl-8 w-full sm:w-64"
              placeholder="Name, code, phone…"
              aria-label="Search customers" maxLength={200}
              value={q}
              onChange={(e) => { setQ(e.target.value); setPage(1); }}
              data-testid="cust-search"
            />
          </div>
          <button
            className="btn-volt inline-flex items-center gap-2"
            disabled={query.isFetching || query.isError || !data}
            onClick={() => setShow("record")}
            data-testid="cust-new"
          >
            <Plus size={14} /> Add customer
          </button>
          <button type="button" className="btn-ghost" disabled={query.isFetching || query.isError || !data} onClick={() => setShow("account")} data-testid="cust-new-account">New customer account</button>
        </div>
      </header>

      <div className="page-body space-y-4">
        <p className="text-sm text-text-secondary">Add customer creates a business record only. New customer account creates a separate new cash customer and login; it never links or merges an existing record. Credit and balances are determined by the server.</p>
        {query.isFetching && <p role="status" data-testid="cust-loading">Loading customers...</p>}
        {query.isError ? <div className="pane p-4 space-y-3" data-testid="cust-error">
          <p role="alert">The customer directory could not be loaded. Check your session and retry.</p>
          <button type="button" className="btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>Retry customers</button>
        </div> : data ? <><div className="pane overflow-x-auto mobile-cards">
          <table className="grid" data-testid="cust-table">
            <caption className="sr-only">Customer business records and server-calculated balances</caption>
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Business</th>
                <th>Phone</th>
                <th>Type</th>
                <th className="text-right">Credit limit</th>
                <th className="text-right">Account balance</th>
                <th className="text-right">Credit held</th>
                <th className="text-right">Available credit</th>
                <th className="text-right">Advance balance</th>
              </tr>
            </thead>
            <tbody>
              {!data?.items?.length && (
                <tr>
                  <td colSpan={10} className="text-text-secondary">
                      <span role="status" data-testid="cust-empty">{search ? "No customers match this search." : "No customers yet."}</span>
                  </td>
                </tr>
              )}
              {data?.items?.map((c) => {
                return (
                  <tr key={c.id} data-testid={`cust-row-${c.id}`}>
                    <td data-label="Code"><span className="min-w-0 break-all">{c.code}</span></td>
                    <td data-label="Name"><span className="min-w-0 break-words">{c.name}</span></td>
                    <td data-label="Business"><span className="min-w-0 break-words">{c.business_name || "Not provided"}</span></td>
                    <td data-label="Phone"><span className="min-w-0 break-all">{c.phone || "Not provided"}</span></td>
                    <td data-label="Type">
                      {c.customer_type === "credit" ? (
                        <span className="chip chip-warning">Credit</span>
                      ) : (
                        <span className="chip chip-info">Cash</span>
                      )}
                    </td>
                    <td data-label="Credit limit" className="text-right">
                      {formatINR(c.credit_limit)}
                    </td>
                    <td data-label="Account balance" className="text-right">
                      {formatINR(c.outstanding)}
                    </td>
                    <td data-label="Credit held" className="text-right">{formatINR(c.credit_held)}</td>
                    <td data-label="Available credit" className="text-right">{formatINR(c.available_credit)}</td>
                    <td data-label="Advance balance" className="text-right">{formatINR(c.advance_balance)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <nav aria-label="Customer pages" className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-ghost" disabled={page === 1 || query.isFetching} onClick={() => setPage(page - 1)}>Previous customers</button>
          <p role="status" className="text-sm">Page {page}{typeof data.total === "number" ? ` / ${data.total} customers` : ""}</p>
          <button type="button" className="btn-ghost" disabled={query.isFetching || typeof data.total !== "number" || page * 200 >= data.total} onClick={() => setPage(page + 1)}>Next customers</button>
        </nav></> : null}
      </div>

      {show === "record" && <NewCustomerModal key={scope} scope={scope} onClose={() => setShow(null)} onDone={done} />}
      {show === "account" && <NewCustomerAccountModal key={scope} scope={scope} onClose={() => setShow(null)} onDone={done} />}
    </div>
  );
}

const customerSchema = z.object({
  name: z.string().trim().min(1, "Enter a customer name.").max(200),
  business_name: z.string().trim().max(200), phone: z.string().trim().max(30),
  email: z.string().trim().max(200).refine((value) => !value || accountEmailSchema.safeParse(value).success, "Enter a valid contact email or leave it blank."),
  gstin: z.string().trim().max(20), address: z.string().trim().max(500),
  city: z.string().trim().max(120), state: z.string().trim().max(120), pincode: z.string().trim().max(15),
  customer_type: z.enum(["cash", "credit"]),
  credit_limit: z.string().trim().refine((value) => moneyInput(value) !== null, "Enter a non-negative decimal with at most two decimal places, without commas."),
  price_tier: z.string().trim().max(30),
});
type CustomerFields = z.infer<typeof customerSchema>;
const customerFields = [
  ["name", "Name *", 200, "text", "cust-name"], ["business_name", "Business name", 200, "text", "cust-business"],
  ["phone", "Phone (optional)", 30, "tel", "cust-phone"], ["email", "Contact email (optional)", 200, "email", "cust-email"],
  ["gstin", "GSTIN", 20, "text", "cust-gstin"], ["price_tier", "Price tier", 30, "text", "cust-tier"],
  ["address", "Address", 500, "text", "cust-address"], ["city", "City", 120, "text", "cust-city"],
  ["state", "State", 120, "text", "cust-state"], ["pincode", "Pincode", 15, "text", "cust-pincode"],
] as const;

function NewCustomerModal({ scope, onClose, onDone }: { scope: string; onClose: () => void; onDone: () => void }) {
  const { register, handleSubmit, formState: { isValid, errors } } = useForm<CustomerFields>({
    resolver: zodResolver(customerSchema), mode: "onChange",
    defaultValues: { name: "", business_name: "", phone: "", email: "", gstin: "", address: "", city: "", state: "", pincode: "", customer_type: "cash", credit_limit: "0", price_tier: "" },
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); };
  }, []);
  async function submit(form: CustomerFields) {
    if (!mounted.current || pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(null);
    try {
      requireCustomerSession(scope);
      const result = await api.post("/customers", {
        ...form, business_name: form.business_name || null, phone: form.phone || null, email: form.email || null,
        gstin: form.gstin || null, address: form.address || null, city: form.city || null, state: form.state || null,
        pincode: form.pincode || null, price_tier: form.price_tier || null,
      }, { signal: controller.signal });
      requireCustomerSession(scope);
      if (!mounted.current) return;
      if (result.status !== 201) throw new Error("Customer creation could not be confirmed.");
      toast.success("Customer business record created. No login was created.");
      onDone();
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted && !axios.isCancel(failure)) setError(customerRequestError(failure));
    } finally {
      if (pending.current === controller) pending.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  return <Modal open busy={busy} onClose={onClose} labelledBy="cust-title" testId="cust-modal">
    <p className="data-label">Add customer / Business record only</p>
    <h2 id="cust-title" className="font-display text-2xl font-bold mt-1 mb-3">New customer record</h2>
    <p className="text-sm text-text-secondary mb-4">This record does not create a login, verify contact email, or link an existing account.</p>
    <form noValidate onSubmit={(event) => void handleSubmit(submit)(event)} aria-busy={busy} onChange={() => setError(null)}>
      <fieldset disabled={busy} className="grid grid-cols-1 sm:grid-cols-2 gap-3 min-w-0">
        {customerFields.map(([name, label, length, type, id]) => <div key={name} className={name === "address" ? "sm:col-span-2" : ""}>
          <label className="data-label" htmlFor={id}>{label}</label>
          <input id={id} className="input mt-1" type={type} maxLength={length} data-testid={id} aria-invalid={!!errors[name]}
            {...register(name, { setValueAs: (value: string) => name === "gstin" ? value.toUpperCase() : value })} />
          {errors[name] && <p role="alert" className="text-sm">{errors[name]?.message}</p>}
        </div>)}
        <div><label className="data-label" htmlFor="cust-type">Type</label>
          <select id="cust-type" className="input mt-1" data-testid="cust-type" {...register("customer_type")}><option value="cash">Cash</option><option value="credit">Credit</option></select></div>
        <div><label className="data-label" htmlFor="cust-limit">Credit limit (INR)</label>
          <input id="cust-limit" className="input mt-1" inputMode="decimal" maxLength={15} data-testid="cust-limit" aria-invalid={!!errors.credit_limit} {...register("credit_limit")} />
          {errors.credit_limit && <p role="alert" className="text-sm">{errors.credit_limit.message}</p>}</div>
      </fieldset>
      {error && <p role="alert" className="text-sm text-status-alert mt-4" data-testid="cust-form-error">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2 mt-5">
        <button type="button" className="btn-ghost" disabled={busy} onClick={onClose} data-testid="cust-cancel">Cancel</button>
        <button type="submit" className="btn-volt" disabled={busy || !isValid} data-testid="cust-submit">{busy ? "Saving..." : "Create customer record"}</button>
      </div>
    </form>
  </Modal>;
}

const customerAccountSchema = z.object({
  email: accountEmailSchema, password: accountPasswordSchema,
  full_name: z.string().trim().min(2).max(200), phone: z.string().trim().max(30), business_name: z.string().trim().max(200),
  confirmed: z.boolean().refine(Boolean, "Confirm new account creation and the holder's private password."),
});
type CustomerAccountFields = z.infer<typeof customerAccountSchema>;

function NewCustomerAccountModal({ scope, onClose, onDone }: { scope: string; onClose: () => void; onDone: () => void }) {
  const { register, handleSubmit, resetField, setValue, formState: { isValid, errors } } = useForm<CustomerAccountFields>({
    resolver: zodResolver(customerAccountSchema), mode: "onChange",
    defaultValues: { email: "", password: "", full_name: "", phone: "", business_name: "", confirmed: false },
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); };
  }, []);
  async function submit(form: CustomerAccountFields) {
    if (!mounted.current || pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(null); resetField("password", { defaultValue: "" }); setValue("confirmed", false);
    try {
      requireCustomerSession(scope);
      const result = await api.post("/auth/register-customer", {
        email: form.email.toLowerCase(), password: form.password, full_name: form.full_name,
        phone: form.phone || null, business_name: form.business_name || null,
      }, { signal: controller.signal });
      requireCustomerSession(scope);
      if (!mounted.current) return;
      if (result.status !== 201) throw new Error("Account creation could not be confirmed.");
      toast.success("New cash customer and login account created. Email is unverified; no invitation was sent. The holder must sign in separately.");
      onDone();
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted && !axios.isCancel(failure)) setError(customerRequestError(failure, true));
    } finally {
      if (pending.current === controller) pending.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  return <Modal open busy={busy} onClose={onClose} labelledBy="cust-account-title" testId="cust-account-modal">
    <h2 id="cust-account-title" className="font-display text-2xl font-bold mb-3">New customer account</h2>
    <p className="text-sm text-text-secondary mb-4">Creates a NEW cash customer business record and linked customer login. Existing profiles and emails are not merged or linked. Email remains unverified; no invitation or automatic login is provided.</p>
    <form noValidate onSubmit={(event) => void handleSubmit(submit)(event)} aria-busy={busy} onChange={(event) => {
      setError(null);
      if ((event.target as HTMLInputElement).name !== "confirmed") setValue("confirmed", false, { shouldValidate: true });
    }}>
      <fieldset disabled={busy} className="space-y-4 min-w-0">
        {([ ["full_name", "Account holder full name *", "text", 200], ["email", "Login email *", "email", 200], ["phone", "Phone (optional)", "tel", 30], ["business_name", "Business name (optional)", "text", 200] ] as const).map(([name, label, type, length]) => <div key={name}>
          <label className="data-label" htmlFor={`cust-account-${name}`}>{label}</label>
          <input id={`cust-account-${name}`} className="input mt-1" type={type} maxLength={length} autoComplete="off" data-testid={`cust-account-${name}`}
            aria-invalid={!!errors[name]} {...register(name)} />
          {errors[name] && <p role="alert" className="text-sm">{errors[name]?.message}</p>}
        </div>)}
        <div><label className="data-label" htmlFor="cust-account-password">Account holder&apos;s final private password *</label>
          <input id="cust-account-password" className="input mt-1" type="password" autoComplete="new-password" maxLength={72}
            data-testid="cust-account-password" aria-describedby="cust-account-password-help" aria-invalid={!!errors.password} {...register("password")} />
          <p id="cust-account-password-help" className="text-xs text-text-secondary mt-2">Privately entered by the holder: at least 12 characters, up to 72 UTF-8 bytes. No generated or temporary credentials; cleared on submission, including failures.</p>
          {errors.password && <p role="alert" className="text-sm">{errors.password.message}</p>}</div>
        <label className="flex items-start gap-3 text-sm" htmlFor="cust-account-confirmed">
          <input id="cust-account-confirmed" type="checkbox" className="mt-1 h-4 w-4 shrink-0" data-testid="cust-account-confirmed" {...register("confirmed")} />
          <span>I confirm this is a new customer and the account holder chose and privately entered this final password.</span>
        </label>
      </fieldset>
      {error && <p role="alert" className="text-sm text-status-alert mt-4" data-testid="cust-account-error">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2 mt-5">
        <button type="button" className="btn-ghost" disabled={busy} onClick={onClose} data-testid="cust-account-cancel">Cancel</button>
        <button type="submit" className="btn-volt" disabled={busy || !isValid} data-testid="cust-account-submit">{busy ? "Creating..." : "Create new customer account"}</button>
      </div>
    </form>
  </Modal>;
}
