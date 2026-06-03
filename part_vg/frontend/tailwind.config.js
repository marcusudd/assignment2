/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        midgard: "#050705",
        asgard: "#0d130e",
        bifrost: "#39ff14",
        heimdall: "#1b4322",
      },
      boxShadow: {
        neon: "0 0 8px rgba(57, 255, 20, 0.35), 0 0 24px rgba(57, 255, 20, 0.15)",
        "neon-soft": "0 0 20px rgba(57, 255, 20, 0.2), inset 0 1px 0 rgba(255,255,255,0.06)",
        "neon-lg": "0 0 16px rgba(57, 255, 20, 0.4), 0 0 48px rgba(57, 255, 20, 0.12)",
        glass: "0 8px 32px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.05)",
        "glass-inset": "inset 0 2px 8px rgba(0, 0, 0, 0.35), inset 0 -1px 0 rgba(255, 255, 255, 0.04)",
        "rim-glow": "0 0 0 1px rgba(57, 255, 20, 0.35), 0 0 20px rgba(57, 255, 20, 0.25), 0 8px 24px rgba(0,0,0,0.4)",
        pill: "inset 0 1px 2px rgba(255,255,255,0.08), 0 4px 12px rgba(0,0,0,0.35)",
      },
      backgroundImage: {
        "panel-gradient":
          "linear-gradient(145deg, rgba(13,19,14,0.9) 0%, rgba(5,7,5,0.95) 100%)",
        "bifrost-glow":
          "radial-gradient(ellipse 80% 60% at 50% 100%, rgba(57,255,20,0.18) 0%, transparent 70%)",
      },
    },
  },
  plugins: [],
};
