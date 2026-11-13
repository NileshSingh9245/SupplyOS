import type { Metadata } from "next";
import type { ReactNode } from "react";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Pricing | SupplyOS", robots: { index: false, follow: false } };

export default function PricingLayout({ children }: { children: ReactNode }) {
  return children;
}
