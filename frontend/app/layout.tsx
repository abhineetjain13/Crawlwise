import "./globals.css";
import { AppShell } from "../components/layout/app-shell";
import { QueryProvider } from "../components/ui/query-provider";
import { Inter, JetBrains_Mono } from "next/font/google";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  weight: ["400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  weight: ["400", "500", "600"],
});

// Runs before first paint to set theme and matching bg — prevents FOUC
const themeScript = `
  (() => {
    const stored = window.localStorage.getItem("crawlerai-theme");
    const dark = stored === "dark";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.style.background = dark ? "#111111" : "#f6f8fc";
  })();
`;

/**
 * Defines the root HTML layout for the application and wraps the app with providers and theme initialization.
 * @example
 * RootLayout({ children: <App /> })
 * <html>...</html>
 * @param {{React.ReactNode}} children - The React node tree to render inside the application shell.
 * @returns {JSX.Element} The root layout element for the app.
 **/
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning data-scroll-behavior="smooth">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className={`${inter.variable} ${jetbrainsMono.variable}`}>
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
