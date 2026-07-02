import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Paleta "terminal financeiro" — quase-preto com fundo levemente
        // esverdeado (livro-caixa à luz de mesa), acento dourado (valor/
        // dividendos), sem nada de roxo/azul genérico de IA.
        bg: {
          DEFAULT: "#0B0F0E",
          surface: "#121816",
          elevated: "#161D1A",
        },
        ink: {
          DEFAULT: "#E8E6DE",
          muted: "#9AA39E",
          faint: "#5C645F",
        },
        gold: {
          DEFAULT: "#C9A227",
          hover: "#D9B445",
          muted: "#7A6520",
        },
        positive: "#4FA37D",
        negative: "#C1554D",
        hairline: "#232B27",
      },
      fontFamily: {
        // Fallbacks de qualidade já deixam isso bonito sem internet.
        // No seu PC (com internet livre), troque por next/font/google —
        // veja o comentário em app/layout.tsx.
        display: ["Fraunces", "Iowan Old Style", "Palatino Linotype", "Georgia", "serif"],
        body: [
          "IBM Plex Sans",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
        mono: [
          "IBM Plex Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      animation: {
        "fade-in": "fadeIn 0.25s ease-out",
        "blink-cursor": "blinkCursor 1s step-end infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        blinkCursor: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
