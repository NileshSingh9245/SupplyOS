import 'package:flutter/material.dart';
import 'package:supplyos_core/supplyos_core.dart';

const ownerRole = 'super_admin';
const managerRole = 'warehouse_manager';
const accountantRole = 'accountant';
const operators = {ownerRole, managerRole};
const financeWriters = {ownerRole, accountantRole};
const adminRoles = {ownerRole, managerRole, accountantRole};

class AdminDestination {
  const AdminDestination(this.path, this.label, this.icon, this.roles);
  final String path;
  final String label;
  final IconData icon;
  final Set<String> roles;
}

// Same ordering and role filtering as frontend/src/lib/navigation.ts.
const adminDestinations = [
  AdminDestination('/dashboard', 'Overview', Icons.space_dashboard_outlined, {
    ownerRole,
  }),
  AdminDestination(
    '/inventory',
    'Inventory',
    Icons.inventory_2_outlined,
    operators,
  ),
  AdminDestination(
    '/warehouses',
    'Warehouses',
    Icons.warehouse_outlined,
    operators,
  ),
  AdminDestination('/products', 'Products', Icons.category_outlined, operators),
  AdminDestination('/pricing', 'Pricing', Icons.sell_outlined, adminRoles),
  AdminDestination('/staff', 'Staff', Icons.badge_outlined, {ownerRole}),
  AdminDestination(
    '/customers',
    'Customers',
    Icons.people_outline,
    financeWriters,
  ),
  AdminDestination('/orders', 'Orders', Icons.receipt_long_outlined, operators),
  AdminDestination(
    '/deliveries',
    'Deliveries',
    Icons.local_shipping_outlined,
    operators,
  ),
  AdminDestination(
    '/finance',
    'Finance',
    Icons.account_balance_wallet_outlined,
    financeWriters,
  ),
  AdminDestination('/ai-supervisor', 'AI Supervisor', Icons.insights_outlined, {
    ownerRole,
  }),
  AdminDestination('/settings', 'Rules & Settings', Icons.tune, {ownerRole}),
];

List<AdminDestination> destinationsFor(String role) => List.unmodifiable(
  adminDestinations.where((item) => item.roles.contains(role)),
);

String homeFor(String role) => switch (role) {
  managerRole => '/inventory',
  accountantRole => '/finance',
  _ => '/dashboard',
};

bool canVisit(String role, String path) =>
    adminRoles.contains(role) &&
    (path == '/intents' ||
        destinationsFor(
          role,
        ).any((item) => path == item.path || path.startsWith('${item.path}/')));

void requireRoles(SessionKey scope, Set<String> roles) {
  if (!roles.contains(scope.role)) {
    throw const AppFailure(FailureKind.forbidden);
  }
}
