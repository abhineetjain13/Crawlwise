import "./globals.css";
import { AppShell } from "../components/layout/app-shell";
import { QueryProvider } from "../components/ui/query-provider";
import { Inter } from "next/font/google";
import localFont from "next/font/local";

const mainFont = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  weight: ["400", "500", "600", "700"],
});

const cascadiaMono = localFont({
  src: [
    { path: "../public/fonts/CascadiaMono-400.ttf", weight: "400" },
    { path: "../public/fonts/CascadiaMono-500.ttf", weight: "500" },
    { path: "../public/fonts/CascadiaMono-600.ttf", weight: "600" },
  ],
  variable: "--font-cascadia-mono",
  display: "swap",
});

// Runs before first paint to set theme and prevent FOUC
const themeScript = `
  (() => {
    const stored = window.localStorage.getItem("crawlerai-theme");
    const dark = stored === "dark" || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  })();
`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning data-scroll-behavior="smooth">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className={`${mainFont.variable} ${cascadiaMono.variable}`}>
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
