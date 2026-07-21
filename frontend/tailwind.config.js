/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        abyss:    "#060912",
        deep:     "#0a101e",
        surface:  "#0e1424",
        surface2: "#141c30",
        line:     "#1f2940",
        line2:    "#2a3654",
        ink:      "#e5e9f0",
        dim:      "#8794ad",
        dim2:     "#5b6886",
        sonar:    "#00e5c0",  // primary accent — cyan/mint
        sonar2:   "#00b894",
        amber:    "#ffb020",
        danger:   "#ff3b5c",
        danger2:  "#c81e3c",
        select:   "#7c9cff",
      },
      fontFamily: {
        display: ["Unbounded", "system-ui", "sans-serif"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        glow: "0 0 32px -8px rgba(0, 229, 192, 0.45)",
        danger: "0 0 32px -8px rgba(255, 59, 92, 0.55)",
      },
      animation: {
        "pulse-slow": "pulse 2.4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scan": "scan 5s linear infinite",
        "fade-in": "fadeIn 360ms ease-out",
      },
      keyframes: {
        scan: {
          "0%":   { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
        fadeIn: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
