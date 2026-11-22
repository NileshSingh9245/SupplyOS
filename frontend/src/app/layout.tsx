import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "SupplyOS — Smart Supply Chain OS",
  description:
    "AI-powered operating system for wholesalers, distributors, and warehouses.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var k='supplyos-theme';var v=localStorage.getItem(k);var m=v==='light'||v==='dark'?v:(window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');var d=document.documentElement;d.classList.toggle('light',m==='light');d.dataset.theme=m;}catch(e){}})();`,
          }}
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
