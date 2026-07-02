import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

// Para usar as fontes reais (Fraunces, IBM Plex Sans, IBM Plex Mono) na sua
// máquina — com internet livre pra baixar do Google Fonts — troque este
// arquivo por algo assim:
//
//   import { Fraunces, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
//   const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-display" });
//   const plexSans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-body" });
//   const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });
//
// E aplique as variáveis: <html className={`${fraunces.variable} ${plexSans.variable} ${plexMono.variable}`}>
// Sem isso, o projeto já funciona com fontes de sistema de boa qualidade
// (configuradas em tailwind.config.ts) — só não terá os tipos exatos.

export const metadata: Metadata = {
  title: "InvestAI",
  description: "Assessor de investimentos baseado em demonstrações financeiras da CVM",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="ledger-texture min-h-screen">{children}</body>
    </html>
  );
}
