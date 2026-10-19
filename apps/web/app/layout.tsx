import type { Metadata } from "next";
import { Archivo, JetBrains_Mono, Rubik } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";

// DESIGN.md: Archivo for display (wdth gives Semi-Condensed), Rubik for every UI role,
// JetBrains Mono for code. globals.css maps the variables to font-display, font-sans, font-mono.
// ponytail: Google Fonts has no Vietnamese subset of Rubik, so letters like ế fall back to the
// system UI font; swap the UI family if that mix shows.
const archivo = Archivo({
  subsets: ["latin", "latin-ext", "vietnamese"],
  axes: ["wdth"],
  variable: "--font-archivo",
});
const rubik = Rubik({ subsets: ["latin", "latin-ext"], variable: "--font-rubik" });
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin", "latin-ext", "vietnamese"],
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "Smart ATS",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi" className={`${archivo.variable} ${rubik.variable} ${jetbrainsMono.variable}`}>
      <body className="bg-surface-canvas-light font-sans text-ink-deep">{children}</body>
    </html>
  );
}
