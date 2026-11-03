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

export const viewport: Viewport = { themeColor: "#1a2129", colorScheme: "light" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>
          <div className="lg:grid lg:grid-cols-[16rem_minmax(0,1fr)] lg:bg-[linear-gradient(to_right,var(--color-basalt)_16rem,transparent_16rem)]">
            <SiteHeader />
            <div className="flex min-h-screen min-w-0 flex-col">
              <main id="main" className="mx-auto w-full max-w-[76rem] flex-1 px-5 pt-10 sm:px-10 lg:pt-14">
                {children}
              </main>
              <SiteFooter />
            </div>
          </div>
        </SessionProvider>
      </body>
    </html>
  );
}
