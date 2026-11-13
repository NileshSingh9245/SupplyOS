import type { AuthUser, Role } from "./auth";

const ROUTE_ROLES: Record<string, readonly Role[]> = {
  "/dashboard": ["super_admin"],
  "/inventory": ["super_admin", "warehouse_manager"],
  "/warehouses": ["super_admin", "warehouse_manager"],
  "/products": ["super_admin", "warehouse_manager"],
  "/pricing": ["super_admin", "warehouse_manager", "accountant"],
  "/customers": ["super_admin", "accountant"],
  "/staff": ["super_admin"],
  "/orders": ["super_admin", "warehouse_manager"],
  "/deliveries": ["super_admin", "warehouse_manager"],
  "/finance": ["super_admin", "accountant"],
  "/ai-supervisor": ["super_admin"],
  "/settings": ["super_admin"],
  "/audit": ["super_admin"],
};

export function staffHome(user: AuthUser | null | undefined): string | null {
  if (!user?.is_active) return null;
  switch (user.role) {
    case "super_admin": return "/dashboard";
    case "warehouse_manager": return "/inventory";
    case "accountant": return "/finance";
    default: return null;
  }
}

export function canAccessStaffRoute(user: AuthUser, pathname: string): boolean {
  if (!staffHome(user)) return false;
  const route = Object.keys(ROUTE_ROLES).find(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
  return !!route && ROUTE_ROLES[route].includes(user.role);
}
