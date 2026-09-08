import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e14",
        panel: "#121722",
        panel2: "#171d2b",
        border: "#232b3b",
        muted: "#8b97ad",
        text: "#e6ebf4",
        accent: "#4f9cf9",
        ok: "#3fb950",
        warn: "#d29922",
        bad: "#f85149",
        sev1: "#f85149",
        sev2: "#db6d28",
        sev3: "#d29922",
        sev4: "#8b97ad",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
