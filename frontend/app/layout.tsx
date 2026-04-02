import { IBM_Plex_Mono, Manrope } from "next/font/google";

import "./globals.css";
import { AppShell } from "../components/layout/app-shell";
import { QueryProvider } from "../components/ui/query-provider";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-manrope",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

const themeScript = `
  (() => {
    const stored = window.localStorage.getItem("crawlerai-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = stored === "dark" || stored === "light" ? stored : prefersDark ? "dark" : "light";
  })();
`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${manrope.variable} ${mono.variable}`}>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
