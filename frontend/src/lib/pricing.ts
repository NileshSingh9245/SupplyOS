import axios, { type AxiosResponse } from "axios";
import { queryOptions } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "./api";
import { useAuth, type AuthUser, type Role } from "./auth";
import { moneyInput } from "./finance";

export interface PricingScope { userId: string; tenantId: string; role: Role; sessionVersion: number }
type Permission = "read" | "tiers" | "customers";
const permissions: Record<Permission, readonly Role[]> = {
  read: ["super_admin", "warehouse_manager", "accountant"],
  tiers: ["super_admin", "warehouse_manager"], customers: ["super_admin", "accountant"],
};
export function pricingScope(user: AuthUser | null | undefined, sessionVersion: number): PricingScope | null {
  return user?.is_active && permissions.read.includes(user.role)
    ? { userId: user.id, tenantId: user.tenant_id, role: user.role, sessionVersion } : null;
}
export function canPrice(scope: PricingScope | null, permission: Permission): boolean {
  return scope !== null && permissions[permission].includes(scope.role);
}
export function pricingKey(scope: PricingScope | null) {
  return ["pricing", scope?.tenantId, scope?.userId, scope?.role, scope?.sessionVersion] as const;
}
function requirePricing(scope: PricingScope | null, permission: Permission): asserts scope is PricingScope {
  if (!scope || !pricingIsCurrent(scope) || !canPrice(scope, permission)) {
    throw new axios.CanceledError("Pricing access changed.");
  }
}
export function pricingIsCurrent(scope: PricingScope): boolean {
  const state = useAuth.getState();
  return !!state.user?.is_active && state.user.id === scope.userId && state.user.tenant_id === scope.tenantId &&
    state.user.role === scope.role && state.sessionVersion === scope.sessionVersion;
}
const money = z.string().regex(/^\d{1,12}(?:\.\d{1,2})?$/);
const discount = z.string().regex(/^(?:100(?:\.0{1,2})?|\d{1,2}(?:\.\d{1,2})?)$/);
export const tierSchema = z.object({ id: z.string().uuid(), name: z.string().min(1).max(60), discount_pct: discount });
const customerSchema = z.object({ id: z.string().uuid(), name: z.string().min(1), code: z.string(), price_tier: z.string().nullable(), is_active: z.boolean() });
const productSchema = z.object({ id: z.string().uuid(), name: z.string().min(1), sku: z.string(), unit: z.string() });
const overrideSchema = z.object({ id: z.string().uuid(), customer_id: z.string().uuid(), product_id: z.string().uuid(), price: money });
const quoteSchema = z.object({ customer_id: z.string().uuid(), product_id: z.string().uuid(), price: money });
const pageFields = { total: z.number().int().nonnegative(), page: z.number().int().positive(), page_size: z.literal(50) };
export type Tier = z.infer<typeof tierSchema>;
export type PricingCustomer = z.infer<typeof customerSchema>;
export type Choice = { id: string; label: string };
export const tierFormSchema = z.object({
  name: z.string().trim().min(1, "Enter a tier name.").max(60),
  discount_pct: discount, reviewed: z.boolean().refine((value) => value, "Review the pricing change first."),
});

export function pricingError(error: unknown): string {
  const status = axios.isAxiosError(error) ? error.response?.status : undefined;
  if (status === 401 || status === 403) return "Pricing access is unavailable for this session.";
  if (status === 404) return "This customer, product or tier is unavailable. Refresh pricing.";
  if (status === 409) return "Pricing conflicts with an existing record. Refresh and review it.";
  if (status === 400 || status === 422) return "Review the pricing fields. Names and exact decimal limits are enforced by the server.";
  return "The pricing result could not be confirmed. Refresh and review it before submitting again.";
}
async function requestPricing<T>(scope: PricingScope | null, permission: Permission,
  request: () => Promise<AxiosResponse<unknown>>, schema: z.ZodType<T, unknown>, status = 200): Promise<T> {
  try {
    requirePricing(scope, permission);
    const response = await request();
    requirePricing(scope, permission);
    const result = schema.safeParse(response.data);
    if (!result.success || response.status !== status) throw new Error("Invalid pricing response.");
    return result.data;
  } catch (failure) {
    if (axios.isCancel(failure)) throw failure;
    throw new Error(pricingError(failure));
  }
}
export function tiersQuery(scope: PricingScope | null) {
  return queryOptions({ queryKey: [...pricingKey(scope), "tiers"], enabled: scope !== null, retry: false,
    queryFn: ({ signal }) => requestPricing(scope, "read", () => api.get("/pricing/tiers", { signal }), z.array(tierSchema)) });
}
export function choicesQuery(scope: PricingScope | null, kind: "customers" | "products", page: number, q: string) {
  const schema = kind === "customers"
    ? customerSchema.transform((value): Choice => ({ id: value.id, label: `${value.name} / ${value.code}` }))
    : productSchema.transform((value): Choice => ({ id: value.id, label: `${value.name} / ${value.sku}` }));
  return queryOptions({ queryKey: [...pricingKey(scope), kind, page, q], enabled: canPrice(scope, "customers"), retry: false,
    queryFn: async ({ signal }) => {
      const data = await requestPricing(scope, "customers", () => api.get(`/${kind}`, {
        params: { page, page_size: 50, ...(q ? { q } : {}) }, signal,
      }), z.object({ ...pageFields, items: z.array(schema) }));
      if (data.page !== page || data.items.length > 50) throw new Error("Invalid pricing directory page.");
      return data;
    } });
}
export function pricingCustomerQuery(scope: PricingScope | null, id: string) {
  return queryOptions({ queryKey: [...pricingKey(scope), "customer", id], enabled: canPrice(scope, "customers") && !!id, retry: false,
    queryFn: async ({ signal }) => {
      if (!z.string().uuid().safeParse(id).success) throw new Error("Invalid customer identifier.");
      const data = await requestPricing(scope, "customers", () => api.get(`/customers/${encodeURIComponent(id)}`, { signal }), customerSchema);
      if (data.id !== id) throw new Error("Invalid pricing customer response.");
      return data;
    } });
}
export function overridesQuery(scope: PricingScope | null, customerId: string) {
  return queryOptions({ queryKey: [...pricingKey(scope), "overrides", customerId], enabled: canPrice(scope, "customers") && !!customerId, retry: false,
    queryFn: async ({ signal }) => {
      if (!z.string().uuid().safeParse(customerId).success) throw new Error("Invalid customer identifier.");
      const rows = await requestPricing(scope, "customers", () => api.get(`/customers/${encodeURIComponent(customerId)}/prices`, { signal }), z.array(overrideSchema));
      if (rows.some((row) => row.customer_id !== customerId) || new Set(rows.map((row) => row.product_id)).size !== rows.length) {
        throw new Error("Invalid customer pricing response.");
      }
      return rows;
    } });
}
export function quoteQuery(scope: PricingScope | null, customerId: string, productId: string) {
  return queryOptions({ queryKey: [...pricingKey(scope), "quote", customerId, productId], enabled: canPrice(scope, "customers") && !!customerId && !!productId, retry: false,
    queryFn: async ({ signal }) => {
      if (!z.string().uuid().safeParse(customerId).success || !z.string().uuid().safeParse(productId).success) throw new Error("Invalid pricing identifiers.");
      const data = await requestPricing(scope, "customers", () => api.get("/pricing/resolve", {
        params: { customer_id: customerId, product_id: productId }, signal,
      }), quoteSchema);
      if (data.customer_id !== customerId || data.product_id !== productId) throw new Error("Invalid customer price quote.");
      return data;
    } });
}
export async function saveTier(scope: PricingScope, tier: Tier | null, name: string, value: string, signal: AbortSignal) {
  requirePricing(scope, "tiers");
  const amount = moneyInput(value);
  if (!amount || !discount.safeParse(amount).success || (tier && !tierSchema.safeParse(tier).success) ||
      (!tier && (name.trim().length < 1 || name.trim().length > 30))) throw new Error("Invalid tier fields.");
  const data = await requestPricing(scope, "tiers", () => tier
    ? api.patch(`/pricing/tiers/${tier.id}`, { discount_pct: amount }, { signal })
    : api.post("/pricing/tiers", { name: name.trim(), discount_pct: amount }, { signal }), tierSchema, tier ? 200 : 201);
  if (data.discount_pct !== amount || (tier ? data.id !== tier.id : data.name !== name.trim())) throw new Error("Tier change could not be confirmed.");
  return data;
}
export async function assignCustomerTier(scope: PricingScope, customerId: string, tier: Tier | null, signal: AbortSignal) {
  requirePricing(scope, "customers");
  if (!z.string().uuid().safeParse(customerId).success || (tier && (!tierSchema.safeParse(tier).success || tier.name.length > 30))) throw new Error("Invalid customer tier assignment.");
  const data = await requestPricing(scope, "customers", () => api.patch(`/customers/${customerId}/pricing-tier`, { tier_id: tier?.id ?? null }, { signal }), customerSchema);
  if (data.id !== customerId || data.price_tier !== (tier?.name ?? null)) throw new Error("Customer tier change could not be confirmed.");
  return data;
}
export async function saveOverride(scope: PricingScope, customerId: string, productId: string, value: string, signal: AbortSignal) {
  requirePricing(scope, "customers");
  const price = moneyInput(value);
  if (!price || !z.string().uuid().safeParse(customerId).success || !z.string().uuid().safeParse(productId).success) throw new Error("Invalid customer price fields.");
  const data = await requestPricing(scope, "customers", () => api.post(`/customers/${customerId}/prices`, { product_id: productId, price }, { signal }), overrideSchema);
  if (data.customer_id !== customerId || data.product_id !== productId || data.price !== price) throw new Error("Customer price change could not be confirmed.");
  return data;
}
export async function removeOverride(scope: PricingScope, customerId: string, productId: string, signal: AbortSignal) {
  requirePricing(scope, "customers");
  if (!z.string().uuid().safeParse(customerId).success || !z.string().uuid().safeParse(productId).success) throw new Error("Invalid customer price identifiers.");
  try {
    const result = await api.delete(`/customers/${customerId}/prices/${productId}`, { signal });
    requirePricing(scope, "customers");
    if (result.status !== 204) throw new Error("Customer price removal could not be confirmed.");
  } catch (failure) {
    if (axios.isCancel(failure)) throw failure;
    throw new Error(pricingError(failure));
  }
}
