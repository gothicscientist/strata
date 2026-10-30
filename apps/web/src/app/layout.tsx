import type { Metadata, Viewport } from "next";
import "@fontsource/eb-garamond/400.css";
import "@fontsource/eb-garamond/400-italic.css";
import "@fontsource/eb-garamond/500.css";
import "@fontsource/eb-garamond/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./globals.css";
import { SessionProvider } from "@/components/SessionProvider";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";

export const metadata: Metadata = {
  title: { default: "Strata", template: "%s — Strata" },
  description:
    "A research instrument for population genetics: PCA projection, exploratory admixture fitting and formal qpAdm modelling against a curated ancient-DNA reference library.",
};

export const viewport: Viewport = { themeColor: "#ffffff", colorScheme: "light" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col">
        <SessionProvider>
          <SiteHeader />
          <main id="main" className="mx-auto w-full max-w-[72rem] flex-1 px-5 pt-12 sm:px-8">
            {children}
          </main>
          <SiteFooter />
        </SessionProvider>
      </body>
    </html>
  );
}
