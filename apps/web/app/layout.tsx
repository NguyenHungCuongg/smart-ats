import type { Metadata } from "next";
import { Archivo, Be_Vietnam_Pro, JetBrains_Mono } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";

// DESIGN.md: Archivo for display (wdth gives Semi-Condensed), Be Vietnam Pro for every UI role,
// JetBrains Mono for code. globals.css maps the variables to font-display, font-sans, font-mono.
const archivo = Archivo({
  subsets: ["latin", "latin-ext", "vietnamese"],
  axes: ["wdth"],
  variable: "--font-archivo",
});
// Not a variable font: the weights the UI uses (DESIGN.md type table).
const beVietnamPro = Be_Vietnam_Pro({
  subsets: ["latin", "latin-ext", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-be-vietnam-pro",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin", "latin-ext", "vietnamese"],
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "Smart ATS",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="vi"
      className={`${archivo.variable} ${beVietnamPro.variable} ${jetbrainsMono.variable}`}
    >
      <body className="bg-surface-canvas-light font-sans text-ink-deep">{children}</body>
    </html>
  );
}
