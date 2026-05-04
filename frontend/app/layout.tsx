import type { Metadata } from 'next';
import './globals.css';

import { IBM_Plex_Sans, JetBrains_Mono } from 'next/font/google';

import { AppShell } from '../components/layout/app-shell';
import { QueryProvider } from '../components/ui/query-provider';

// Primary sans — variable name must match globals.css: var(--font-primary-source, 'IBM Plex Sans')
const mainFont = IBM_Plex_Sans({
  subsets: ['latin'],
  variable: '--font-primary-source',
  weight: ['300', '400', '500', '600', '700'],
  style: ['normal', 'italic'],
  display: 'swap',
});

// Mono — variable name must match globals.css: var(--font-jetbrains-mono, 'JetBrains Mono')
const monoFont = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  weight: ['400', '500', '600', '700'],
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'CrawlerAI',
  description: 'Web crawling and structured data extraction platform.',
};

// Runs before first paint — sets data-theme to prevent FOUC
const themeScript = `(()=>{let d=false;try{const s=localStorage.getItem("crawlerai-theme");d=s==="dark"||(!s&&matchMedia("(prefers-color-scheme:dark)").matches);}catch(e){try{d=matchMedia("(prefers-color-scheme:dark)").matches;}catch(_){d=false;}}document.documentElement.dataset.theme=d?"dark":"light";})();`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Inline theme script — must be synchronous to block FOUC */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      {/*
        Only apply font variables here, NOT mainFont.className.
        mainFont.className hardcodes a font-family class directly on body,
        bypassing the CSS variable cascade in globals.css entirely.
        The variables are picked up by --font-primary-family and --font-mono-family.
      */}
      <body className={`${mainFont.variable} ${monoFont.variable}`}>
        <div className="noise-overlay" aria-hidden="true" />
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
