import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatINR(
  value: number | string | null | undefined,
  opts: { decimals?: number; symbol?: string } = {},
): string {
  const { decimals = 2, symbol = "₹" } = opts;
  if (value === null || value === undefined || value === "") return `${symbol}0.00`;
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return `${symbol}0.00`;
  // Indian numbering (lakh, crore)
  return `${symbol}${new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)}`;
}

export function formatQty(
  value: number | string | null | undefined,
  unit: string = "",
): string {
  if (value === null || value === undefined || value === "") return `0 ${unit}`.trim();
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return `0 ${unit}`.trim();
  const trimmed = n % 1 === 0 ? n.toString() : n.toFixed(3).replace(/\.?0+$/, "");
  return unit ? `${trimmed} ${unit}` : trimmed;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch {
    return iso;
  }
}
