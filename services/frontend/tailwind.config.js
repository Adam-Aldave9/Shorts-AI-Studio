/** @type {import('tailwindcss').Config} */
import defaultTheme from "tailwindcss/defaultTheme";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "rgb(var(--color-surface) / <alpha-value>)",
          raised: "rgb(var(--color-surface-raised) / <alpha-value>)",
          overlay: "rgb(var(--color-surface-overlay) / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--color-border) / <alpha-value>)",
          strong: "rgb(var(--color-border-strong) / <alpha-value>)",
        },
        fg: {
          DEFAULT: "rgb(var(--color-fg) / <alpha-value>)",
          muted: "rgb(var(--color-fg-muted) / <alpha-value>)",
          subtle: "rgb(var(--color-fg-subtle) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          strong: "rgb(var(--color-accent-strong) / <alpha-value>)",
          soft: "rgb(var(--color-accent-soft) / <alpha-value>)",
        },
        success: "rgb(var(--color-success) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        warning: "rgb(var(--color-warning) / <alpha-value>)",
        info: "rgb(var(--color-info) / <alpha-value>)",
        chart: {
          1: "rgb(var(--color-chart-1) / <alpha-value>)",
          2: "rgb(var(--color-chart-2) / <alpha-value>)",
        },
      },
      borderColor: {
        // Makes every existing bare `border` class use the token hairline.
        DEFAULT: "rgb(var(--color-border) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["InterVariable", "Inter", ...defaultTheme.fontFamily.sans],
      },
      keyframes: {
        "dag-flow": { to: { "stroke-dashoffset": "-32" } },
        "node-pulse": {
          "0%, 100%": { opacity: "0.35" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "dag-flow": "dag-flow 1.6s linear infinite",
        "node-pulse": "node-pulse 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
