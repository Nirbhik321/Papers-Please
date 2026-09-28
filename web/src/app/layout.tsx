import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { SiteHeader } from "@/components/SiteHeader";
import { themeScript } from "@/components/ThemeToggle";
import "./globals.css";

const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], weight: ["500", "600"] });
const plexSans = IBM_Plex_Sans({ variable: "--font-plex-sans", subsets: ["latin"], weight: ["400", "500", "600"] });
const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: { default: "Papers Please — VTU questions that keep coming back", template: "%s · Papers Please" },
  description:
    "Every past VTU question paper, grouped by question and ranked by how often it repeats. Pick your subject, grab the cheat sheet, study what counts.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning
      className={`${fraunces.variable} ${plexSans.variable} ${plexMono.variable} h-full antialiased`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex min-h-full min-w-[1280px] flex-col bg-paper text-ink">
        <SiteHeader />
        <div className="flex-grow">{children}</div>
        <footer data-site-footer className="mt-16 border-t border-line">
          <div className="mx-auto flex max-w-[1440px] justify-between gap-8 px-20 py-8 text-sm text-ink-2">
            <span>Papers Please — built by students, for VTU students.</span>
            <span>Rankings show how often topics repeated. They are not a guarantee of what will appear.</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
