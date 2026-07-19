import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";

export const metadata: Metadata = {
  title: "SupplyOS — Smart Supply Chain OS",
  description: "AI-powered operating system for wholesalers, distributors, and warehouses.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
        <Toaster
          theme="dark"
          position="top-right"
          toastOptions={{
            style: {
              background: "#141414",
              border: "1px solid #2E2E2E",
              color: "#fff",
              borderRadius: 2,
            },
          }}
        />
      </body>
    </html>
  );
}
