import type { Metadata } from "next";
import { ChangePassword } from "@/features/auth/change-password";

export const metadata: Metadata = { title: "Change Password | SupplyOS" };

export default function ChangePasswordPage() {
  return <ChangePassword />;
}
