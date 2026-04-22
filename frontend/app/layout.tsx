import"./globals.css";
import { AppShell } from"../components/layout/app-shell";
import { QueryProvider } from"../components/ui/query-provider";
import { Inter, JetBrains_Mono } from"next/font/google";

const mainFont = Inter({
 subsets: ["latin"],
 variable:"--font-inter",
 weight: ["400","500","600","700"],
});

const jetbrainsMono = JetBrains_Mono({
 subsets: ["latin"],
 variable: "--font-jetbrains-mono",
 display: "swap",
});

// Runs before first paint to set theme and prevent FOUC
const themeScript = `
 (() => {
 const stored = window.localStorage.getItem("crawlerai-theme");
 const dark = stored ==="dark"|| (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches);
 document.documentElement.dataset.theme = dark ?"dark":"light";
 })();
`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
 return (
 <html lang="en"suppressHydrationWarning data-scroll-behavior="smooth">
 <head>
 <script dangerouslySetInnerHTML={{ __html: themeScript }} />
 </head>
 <body className={`${mainFont.variable} ${jetbrainsMono.variable}`}>
 <QueryProvider>
 <AppShell>{children}</AppShell>
 </QueryProvider>
 </body>
 </html>
 );
}
