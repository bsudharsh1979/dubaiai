import type { Metadata, Viewport } from "next";
import "./globals.css";
import { I18nProvider } from "@/lib/i18n";
import { SessionProvider } from "@/lib/session";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "RainReady UAE — Sovereign Water & HSE Command (prototype)",
  description: "Decision-support prototype for water anomalies, flood risk and human-approved response. Synthetic data; simulated connectors; not an official system.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <body className="min-h-full antialiased">
        <I18nProvider>
          <SessionProvider>
            <Shell>{children}</Shell>
          </SessionProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
