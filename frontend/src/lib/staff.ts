import axios from "axios";
import { queryOptions } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "./api";
import { useAuth, type AuthUser } from "./auth";

export const staffRoles = ["warehouse_manager", "accountant", "delivery_partner"] as const;
export type StaffRole = typeof staffRoles[number];
export const staffRoleLabels: Record<StaffRole, string> = {
  warehouse_manager: "Warehouse manager", accountant: "Accountant", delivery_partner: "Delivery partner",
};

export const accountEmailSchema = z.string().trim().max(200).email("Enter a valid email address.");
export const accountPasswordSchema = z.string().refine(
  (value) => {
    const characters = Array.from(value);
    // TextEncoder replaces lone surrogates; the server requires strict UTF-8.
    return characters.length >= 12 && characters.every((character) => {
      const point = character.codePointAt(0)!;
      return point < 0xd800 || point > 0xdfff;
    }) && new TextEncoder().encode(value).length <= 72;
  },
  "Use at least 12 characters and no more than 72 UTF-8 bytes.",
);
export const staffDetailsSchema = z.object({
  full_name: z.string().trim().min(2, "Enter a full name of at least 2 characters.").max(200),
  phone: z.string().trim().max(30),
  role: z.enum(staffRoles),
});

const staffMemberSchema = z.object({
  id: z.string().min(1), email: z.string(), full_name: z.string(), phone: z.string().nullable(),
  role: z.enum(staffRoles), is_active: z.boolean(), created_at: z.string().datetime({ offset: true }),
});
const staffPageSchema = z.object({
  items: z.array(staffMemberSchema), total: z.number().int().nonnegative(),
  page: z.number().int().positive(), page_size: z.number().int().min(1).max(200),
});
export type StaffMember = z.infer<typeof staffMemberSchema>;
export type StaffCreate = z.infer<typeof staffDetailsSchema> & { email: string; password: string };
export type StaffPatch = Partial<Pick<StaffMember, "full_name" | "phone" | "role" | "is_active">>;
export interface StaffScope { userId: string; tenantId: string; sessionVersion: number }

export function staffScope(user: AuthUser | null | undefined, sessionVersion: number): StaffScope | null {
  return user?.is_active && user.role === "super_admin"
    ? { userId: user.id, tenantId: user.tenant_id, sessionVersion } : null;
}

function requireOwner(scope: StaffScope | null, targetId?: string): asserts scope is StaffScope {
  const state = useAuth.getState();
  if (!scope || !state.user?.is_active || state.user.role !== "super_admin" ||
      state.user.id !== scope.userId || state.user.tenant_id !== scope.tenantId ||
      state.sessionVersion !== scope.sessionVersion || targetId === scope.userId) {
    throw new axios.CanceledError("Staff access is unavailable for this session.");
  }
}

export function staffQuery(scope: StaffScope | null, page: number) {
  return queryOptions({
    queryKey: ["staff", scope?.tenantId, scope?.userId, scope?.sessionVersion, page],
    enabled: scope !== null,
    retry: false,
    queryFn: async ({ signal }) => {
      try {
        requireOwner(scope);
        const { data } = await api.get<unknown>("/staff", { params: { page, page_size: 50 }, signal });
        requireOwner(scope);
        // Neither extra DTO fields nor reflected error bodies belong in the cache.
        const result = staffPageSchema.safeParse(data);
        if (!result.success || result.data.page !== page || result.data.page_size !== 50 ||
            result.data.items.some((item) => item.id === scope.userId)) throw new Error("Invalid staff response.");
        return result.data;
      } catch (failure) {
        if (axios.isCancel(failure)) throw failure;
        throw new Error(staffRequestError(failure));
      }
    },
  });
}

export async function createStaff(scope: StaffScope, form: StaffCreate, signal: AbortSignal) {
  requireOwner(scope);
  const parsed = staffDetailsSchema.extend({ email: accountEmailSchema, password: accountPasswordSchema }).safeParse(form);
  if (!parsed.success) throw new Error("Invalid staff fields or password policy.");
  const values = parsed.data;
  const response = await api.post<unknown>("/staff", {
    email: values.email.toLowerCase(), full_name: values.full_name,
    phone: values.phone || null, role: values.role, password: values.password,
  }, { signal });
  requireOwner(scope);
  const result = staffMemberSchema.safeParse(response.data);
  if (!result.success || response.status !== 201 || result.data.email !== values.email.toLowerCase() || result.data.role !== values.role) {
    throw new Error("Staff creation could not be confirmed.");
  }
  return result.data;
}

export async function patchStaff(scope: StaffScope, id: string, patch: StaffPatch, signal: AbortSignal) {
  requireOwner(scope, id);
  const payload: StaffPatch = {};
  if (patch.full_name !== undefined) payload.full_name = patch.full_name.trim();
  if (patch.phone !== undefined) payload.phone = patch.phone?.trim() || null;
  if (patch.role !== undefined) payload.role = patch.role;
  if (patch.is_active !== undefined) payload.is_active = patch.is_active;
  if (!Object.keys(payload).length) throw new Error("No staff changes supplied.");
  const parsed = z.object({
    full_name: staffDetailsSchema.shape.full_name.optional(), phone: z.string().max(30).nullable().optional(),
    role: z.enum(staffRoles).optional(), is_active: z.boolean().optional(),
  }).safeParse(payload);
  if (!parsed.success) throw new Error("Invalid staff changes.");
  const response = await api.patch<unknown>(`/staff/${encodeURIComponent(id)}`, parsed.data, { signal });
  requireOwner(scope, id);
  const result = staffMemberSchema.safeParse(response.data);
  if (!result.success || response.status !== 200 || result.data.id !== id) throw new Error("Staff changes could not be confirmed.");
  return result.data;
}

export async function revokeStaffSessions(scope: StaffScope, id: string, signal: AbortSignal) {
  requireOwner(scope, id);
  const response = await api.post(`/staff/${encodeURIComponent(id)}/revoke-sessions`, {}, { signal });
  requireOwner(scope, id);
  if (response.status !== 200 || response.data?.message !== "Staff sessions revoked") {
    throw new Error("Staff session revocation could not be confirmed.");
  }
}

export function staffRequestError(error: unknown): string {
  const status = axios.isAxiosError(error) ? error.response?.status : undefined;
  if (status === 401 || status === 403) return "Only the signed-in owner may manage staff. Check your session.";
  if (status === 404) return "This staff member is unavailable. Refresh the directory.";
  if (status === 409) return "This email is already registered. No new account was created or linked.";
  if (status === 400 || status === 422) return "Review the account fields and password policy before trying again.";
  return "The staff request could not be confirmed. Refresh the directory before retrying.";
}
