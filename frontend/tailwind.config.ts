import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx,js,jsx,mdx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "#0A0A0A",
        surface1: "#141414",
        surface2: "#1F1F1F",
        border: "#2E2E2E",
        borderActive: "#4A4A4A",
        text: {
          primary: "#FFFFFF",
          secondary: "#A3A3A3",
          tertiary: "#737373",
        },
        volt: {
          DEFAULT: "#D4FF00",
          hover: "#B3D600",
          ink: "#000000",
        },
        status: {
          alert: "#FF3B30",
          warning: "#FFD600",
          success: "#34C759",
          info: "#007AFF",
        },
      },
      fontFamily: {
        display: ['"Cabinet Grotesk"', '"IBM Plex Sans"', "system-ui", "sans-serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      letterSpacing: {
        tightest: "-0.05em",
        widestUp: "0.2em",
      },
      borderRadius: {
        DEFAULT: "0",
        sm: "2px",
        md: "4px",
      },
    },
  },
  plugins: [],
};

export default config;
