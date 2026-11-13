"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import axios from "axios";
import { useQuery } from "@tanstack/react-query";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { accountEmailSchema, accountPasswordSchema } from "@/lib/staff";

const optionalText = (length: number) => z.string().trim().max(length);
const warehouseSchema = z.object({
  code: z.string().trim().min(1).max(30), name: z.string().trim().min(1).max(200),
  city: optionalText(120), state: optionalText(120), pincode: optionalText(15),
});
const setupSchema = z.object({
  company_name: z.string().trim().min(2).max(200), legal_name: optionalText(200),
  gstin: optionalText(20), phone: optionalText(30), address: optionalText(500),
  email: optionalText(200).refine((value) => !value || accountEmailSchema.safeParse(value).success,
    "Enter a valid contact email or leave it blank."),
  currency: z.string().regex(/^[A-Z]{3}$/),
  admin_email: accountEmailSchema, admin_password: accountPasswordSchema,
  admin_full_name: z.string().trim().min(2).max(200),
  setup_authorization: z.string().min(32).max(256).regex(/^[A-Za-z0-9_-]+$/)
    .refine((value) => new Set(value).size >= 12,
      "Enter the valid operator-provided setup authorization."),
  warehouses: z.array(warehouseSchema).min(1).max(50).refine(
    (items) => new Set(items.map((item) => item.code)).size === items.length,
    "Warehouse codes must be unique after trimming; codes are case-sensitive.",
  ),
});
type SetupFields = z.infer<typeof setupSchema>;
const setupStatusSchema = z.object({
  is_setup_complete: z.boolean(), is_initialized: z.boolean(), authorization_configured: z.boolean(),
}).refine((value) => !value.is_setup_complete || value.is_initialized);
const companyFields = ["company_name", "legal_name", "gstin", "phone", "email", "address", "currency"] as const;
const ownerFields = ["admin_full_name", "admin_email", "admin_password", "setup_authorization"] as const;
const blankWarehouse = { code: "WH-1", name: "Main Warehouse", city: "", state: "", pincode: "" };

export default function SetupPage() {
  const router = useRouter();
  const user = useAuth((state) => state.user);
  const bootstrapError = useAuth((state) => state.bootstrapError);
  const bootstrap = useAuth((state) => state.bootstrap);
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<"initialized" | "unconfigured" | null>(null);
  const mounted = useRef(false);
  const pending = useRef<AbortController | null>(null);
  const { register, control, trigger, handleSubmit, resetField, getValues, formState: { errors } } = useForm<SetupFields>({
    resolver: zodResolver(setupSchema), mode: "onChange",
    defaultValues: {
      company_name: "", legal_name: "", gstin: "", phone: "", email: "", address: "", currency: "INR",
      admin_email: "", admin_password: "", admin_full_name: "", setup_authorization: "",
      warehouses: [blankWarehouse],
    },
  });
  const { fields: warehouses, append, remove } = useFieldArray({ control, name: "warehouses" });
  const status = useQuery({
    queryKey: ["setup-status"], retry: false, staleTime: 0,
    queryFn: async ({ signal }) => {
      try {
        const result = setupStatusSchema.safeParse((await api.get("/setup/status", { signal })).data);
        if (!result.success) throw new Error("Invalid setup status.");
        return result.data;
      } catch (failure) {
        if (axios.isCancel(failure)) throw failure;
        throw new Error("Setup status could not be verified.");
      }
    },
  });
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); };
  }, []);
  const canInitialize = user !== undefined && !status.isFetching && !status.isError && !blocked &&
    status.data?.authorization_configured && !status.data.is_initialized && !status.data.is_setup_complete;

  async function nextStep() {
    if (!mounted.current || !canInitialize || pending.current) return;
    if (await trigger(step === 1 ? [...companyFields] : [...ownerFields])) {
      if (mounted.current) { setError(null); setStep(step + 1); }
    }
  }

  async function submit(form: SetupFields) {
    if (!mounted.current || step !== 3 || !canInitialize || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError(null);
    // Private inputs never enter query state, storage, URLs, or retry queues.
    resetField("admin_password", { defaultValue: "" });
    resetField("setup_authorization", { defaultValue: "" });
    try {
      const { setup_authorization, ...body } = form;
      const result = await api.post("/setup/initialize", {
        ...body, legal_name: body.legal_name || null, gstin: body.gstin || null,
        phone: body.phone || null, email: body.email || null, address: body.address || null,
        warehouses: body.warehouses.map((warehouse) => ({
          ...warehouse, city: warehouse.city || null, state: warehouse.state || null, pincode: warehouse.pincode || null,
        })),
      }, { headers: { "X-Setup-Authorization": setup_authorization }, signal: controller.signal });
      if (!mounted.current) return;
      const complete = setupStatusSchema.safeParse(result.data);
      if (result.status !== 201 || !complete.success || !complete.data.is_setup_complete || !complete.data.authorization_configured) {
        throw new Error("Setup result could not be confirmed.");
      }
      toast.success("Setup complete. Please sign in.");
      router.replace("/login");
    } catch (failure) {
      if (!mounted.current || controller.signal.aborted) return;
      const code = axios.isAxiosError(failure) ? failure.response?.status : undefined;
      if (code === 409) setBlocked("initialized");
      if (code === 503) setBlocked("unconfigured");
      setError(code === 403 ? "Setup authorization was rejected. Re-enter the operator-provided authorization and password."
        : code === 409 ? "This instance is already initialized. Setup cannot replace existing data."
        : code === 503 ? "Setup authorization is not configured on the server. Contact the operator."
        : code === 400 || code === 422 ? "Review the setup fields and password policy. Private inputs have been cleared."
        : "The setup result could not be confirmed. Check the instance status before trying again.");
      setStep(2);
      void status.refetch();
    } finally {
      if (pending.current === controller) pending.current = null;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <main className="min-h-screen relative flex items-center justify-center p-6">
      <div
        className="absolute inset-0 -z-0 opacity-30"
        style={{
          backgroundImage: `url(https://images.unsplash.com/photo-1672552226669-f6c3041972ea?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzMzN8MHwxfHNlYXJjaHw0fHxtb2Rlcm4lMjB3YXJlaG91c2UlMjBpbnRlcmlvcnxlbnwwfHx8fDE3ODQ0ODA2NzF8MA&ixlib=rb-4.1.0&q=85)`,
          backgroundSize: "cover", backgroundPosition: "center",
          filter: "grayscale(60%) blur(2px)",
        }}
      />
      <div className="absolute inset-0 bg-bg/85 -z-0" />

      <div className="relative z-10 w-full min-w-0 max-w-3xl pane p-5 sm:p-8 md:p-12" data-testid="setup-wizard">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <p className="data-label">First-launch setup / Step {step} of 3</p>
            <h1 className="font-display text-3xl md:text-4xl font-black tracking-tightest break-words mt-1">
              Configure your SupplyOS
            </h1>
          </div>
          <div className="hidden sm:flex gap-1">
            {[1, 2, 3].map((n) => (
              <span key={n}
                className={`w-8 h-1 ${n <= step ? "bg-volt" : "bg-border"}`}
              />
            ))}
          </div>
        </div>

        {status.isFetching || user === undefined ? (
          <div className="space-y-3">
            <p role="status">Checking instance and session status...</p>
            {bootstrapError && <button type="button" className="btn-ghost" onClick={() => void bootstrap()}>Retry session check</button>}
          </div>
        ) : status.isError ? (
          <div className="space-y-3" data-testid="setup-status-error">
            <p role="alert">Setup status could not be verified. Initialization is disabled.</p>
            <button type="button" className="btn-ghost" onClick={() => void status.refetch()}>Retry status check</button>
          </div>
        ) : status.data?.is_setup_complete ? (
          <div className="space-y-3" data-testid="setup-complete">
            <p role="status">Instance setup is complete. Sign in to continue.</p>
            <Link className="btn-volt inline-flex" href="/login">Sign in</Link>
          </div>
        ) : status.data?.is_initialized || blocked === "initialized" ? (
          <p role="alert" data-testid="setup-initialized">This instance is already initialized, but setup is incomplete or unavailable. Contact the operator; setup cannot replace existing data.</p>
        ) : !status.data?.authorization_configured || blocked === "unconfigured" ? (
          <div className="space-y-3" data-testid="setup-unconfigured">
            <p role="alert">Setup is disabled because setup authorization is not configured on the server. Contact the operator.</p>
            <button type="button" className="btn-ghost" onClick={() => { setBlocked(null); void status.refetch(); }}>Check instance status</button>
          </div>
        ) : (
        <form noValidate onSubmit={(event) => void handleSubmit(submit)(event)} aria-busy={busy} data-testid="setup-form">
          {error && <p role="alert" className="text-sm text-status-alert mb-4" data-testid="setup-error">{error}</p>}
          <fieldset disabled={busy || !canInitialize} className="min-w-0">
          {step === 1 && <div className="space-y-4">
            <div>
              <label className="data-label" htmlFor="setup-company-name">Company / business name *</label>
              <input id="setup-company-name" className="input mt-1" data-testid="setup-company-name" maxLength={200}
                aria-invalid={!!errors.company_name} {...register("company_name")}
                placeholder="e.g. Acme Wholesale Pvt Ltd" />
              {errors.company_name && <p role="alert" className="text-sm">Enter a company name of 2 to 200 characters.</p>}
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              {([
                ["legal_name", "Legal name", 200, "text"], ["gstin", "GSTIN", 20, "text"],
                ["phone", "Contact phone", 30, "tel"], ["email", "Contact email (optional)", 200, "email"],
                ["address", "Address", 500, "text"],
              ] as const).map(([name, label, length, type]) => <div key={name} className={name === "address" ? "md:col-span-2" : ""}>
                <label className="data-label" htmlFor={`setup-${name.replace("_", "-")}`}>{label}</label>
                <input id={`setup-${name.replace("_", "-")}`} className="input mt-1" data-testid={`setup-${name.replace("_", "-")}`}
                  type={type} maxLength={length} aria-invalid={!!errors[name]} {...register(name)} />
                {errors[name] && <p role="alert" className="text-sm">{name === "email" ? "Enter a valid contact email or leave it blank." : `Use no more than ${length} characters.`}</p>}
              </div>)}
            </div>
            <div className="flex justify-end pt-4">
              <button type="button" className="btn-volt" data-testid="setup-next-1" onClick={() => void nextStep()}>Next</button>
            </div>
          </div>}

          {step === 2 && <div className="space-y-4">
            <p className="text-text-secondary text-sm">This owner account has super-admin access. Creating it does not verify email or sign you in.</p>
            <div>
              <label className="data-label" htmlFor="setup-admin-name">Owner full name *</label>
              <input id="setup-admin-name" className="input mt-1" data-testid="setup-admin-name" maxLength={200}
                aria-invalid={!!errors.admin_full_name} {...register("admin_full_name")} />
              {errors.admin_full_name && <p role="alert" className="text-sm">Enter a full name of 2 to 200 characters.</p>}
            </div>
            <div>
              <label className="data-label" htmlFor="setup-admin-email">Owner email *</label>
              <input id="setup-admin-email" className="input mt-1" data-testid="setup-admin-email" type="email" maxLength={200}
                aria-invalid={!!errors.admin_email} {...register("admin_email")} />
              {errors.admin_email && <p role="alert" className="text-sm">Enter a valid owner email address.</p>}
            </div>
            <div>
              <label className="data-label" htmlFor="setup-admin-password">Owner&apos;s final private password *</label>
              <input id="setup-admin-password" className="input mt-1" data-testid="setup-admin-password" type="password"
                autoComplete="new-password" maxLength={72} aria-describedby="setup-password-help"
                aria-invalid={!!errors.admin_password} {...register("admin_password")} />
              <p id="setup-password-help" className="text-xs text-text-secondary mt-2">The owner chooses and privately enters this final password. At least 12 characters, up to 72 UTF-8 bytes.</p>
              {errors.admin_password && <p role="alert" className="text-sm">{errors.admin_password.message}</p>}
            </div>
            <div>
              <label className="data-label" htmlFor="setup-authorization">Setup authorization *</label>
              <input id="setup-authorization" className="input mt-1" type="password" autoComplete="off" maxLength={256}
                data-testid="setup-authorization" aria-describedby="setup-authorization-help"
                aria-invalid={!!errors.setup_authorization} {...register("setup_authorization")} />
              <p id="setup-authorization-help" className="text-xs text-text-secondary mt-2">Provided privately by the operator, not the owner&apos;s password. Sent only in the initialization authorization header; never retrieved automatically.</p>
              {errors.setup_authorization && <p role="alert" className="text-sm">Enter the valid operator-provided authorization: 32 to 256 URL-safe characters, without spaces or commas.</p>}
            </div>
            <div className="flex flex-wrap justify-between gap-2 pt-4">
              <button type="button" className="btn-ghost" data-testid="setup-back-2" onClick={() => setStep(1)}>Back</button>
              <button type="button" className="btn-volt" data-testid="setup-next-2" onClick={() => void nextStep()}>Next</button>
            </div>
          </div>}

          {step === 3 && <div className="space-y-4">
            <p className="text-text-secondary text-sm">Add one or more warehouses. You can add racks/shelves later.</p>
            {warehouses.map((warehouse, index) => <fieldset key={warehouse.id} className="pane min-w-0 p-4" data-testid={`setup-warehouse-${index}`}>
              <legend className="data-label px-1">Warehouse {index + 1}</legend>
              <div className="grid sm:grid-cols-2 gap-3">
                {([ ["code", "Code *", 30], ["name", "Name *", 200], ["city", "City", 120], ["state", "State", 120], ["pincode", "Pincode", 15] ] as const).map(([name, label, length]) => <div key={name} className="min-w-0">
                  <label className="data-label" htmlFor={`setup-warehouse-${index}-${name}`}>{label}</label>
                  <input id={`setup-warehouse-${index}-${name}`} className="input mt-1" maxLength={length}
                    aria-invalid={!!errors.warehouses?.[index]?.[name]} {...register(`warehouses.${index}.${name}`)} />
                  {errors.warehouses?.[index]?.[name] && <p role="alert" className="text-sm">Review this warehouse field (up to {length} characters).</p>}
                </div>)}
              </div>
              {warehouses.length > 1 && <button type="button" className="btn-ghost mt-3" data-testid={`setup-warehouse-remove-${index}`}
                aria-label={`Remove warehouse ${index + 1}`} onClick={() => remove(index)}>Remove warehouse</button>}
            </fieldset>)}
            {errors.warehouses && <p role="alert" className="text-sm">Use 1 to 50 warehouses with names and trimmed, unique, case-sensitive codes.</p>}
            <button type="button" className="btn-ghost text-sm" data-testid="setup-warehouse-add" disabled={warehouses.length >= 50}
              onClick={() => {
                const codes = new Set(getValues("warehouses").map((warehouse) => warehouse.code.trim()));
                let number = warehouses.length + 1;
                while (codes.has(`WH-${number}`)) number += 1;
                append({ ...blankWarehouse, code: `WH-${number}`, name: "" });
              }}>
              + Add another warehouse
            </button>
            <div className="flex flex-wrap justify-between gap-2 pt-4">
              <button type="button" className="btn-ghost" data-testid="setup-back-3" onClick={() => setStep(2)}>Back</button>
              <button type="submit" className="btn-volt" data-testid="setup-finish" disabled={busy || !canInitialize}>
                {busy ? "Setting up..." : "Finish setup"}</button>
            </div>
          </div>}
          </fieldset>
        </form>)}
      </div>
    </main>
  );
}
