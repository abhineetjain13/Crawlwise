import { Inter, JetBrains_Mono } from "next/font/google";
import Script from "next/script";

import "./globals.css";
import { AppShell } from "../components/layout/app-shell";
import { QueryProvider } from "../components/ui/query-provider";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const mono = JetBrains_Mono({
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
      <body className={`${inter.variable} ${mono.variable}`}>
        <Script id="theme-bootstrap" strategy="beforeInteractive">
          {themeScript}
        </Script>
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
