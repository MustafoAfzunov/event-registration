// Theme tokens copied VERBATIM from the Stitch export (docs/stitch_event_registration_app_screens/*/code.html,
// identical in all four screens): colors, borderRadius, spacing, fontSize. The only change is the font stacks:
// the fonts are self-hosted via @fontsource-variable (imported in src/main.tsx), so the family names are the
// "<name> Variable" ones, with the plain names and system fonts as fallbacks.
// NOTE: DESIGN.md lists a different radius scale than the exported config; we follow the exported config
// because the screenshots were rendered with it.
const inter = ["Inter Variable", "Inter", "system-ui", "sans-serif"];
const jakarta = ["Plus Jakarta Sans Variable", "Plus Jakarta Sans", "system-ui", "sans-serif"];

/** @type {import("tailwindcss").Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "on-secondary": "#ffffff",
        "primary": "#3525cd",
        "on-secondary-fixed": "#002113",
        "surface-variant": "#dae2fd",
        "inverse-surface": "#283044",
        "surface": "#faf8ff",
        "on-tertiary-fixed": "#2a1700",
        "on-secondary-fixed-variant": "#005236",
        "tertiary-container": "#885500",
        "on-tertiary": "#ffffff",
        "background": "#faf8ff",
        "surface-container-low": "#f2f3ff",
        "surface-container-lowest": "#ffffff",
        "on-surface": "#131b2e",
        "surface-container": "#eaedff",
        "on-error-container": "#93000a",
        "on-background": "#131b2e",
        "tertiary": "#684000",
        "on-primary-container": "#dad7ff",
        "error": "#ba1a1a",
        "on-tertiary-fixed-variant": "#653e00",
        "secondary-container": "#6cf8bb",
        "surface-container-highest": "#dae2fd",
        "on-secondary-container": "#00714d",
        "primary-fixed": "#e2dfff",
        "surface-tint": "#4d44e3",
        "on-primary": "#ffffff",
        "error-container": "#ffdad6",
        "on-tertiary-container": "#ffd4a4",
        "on-primary-fixed-variant": "#3323cc",
        "on-surface-variant": "#464555",
        "outline-variant": "#c7c4d8",
        "primary-fixed-dim": "#c3c0ff",
        "inverse-on-surface": "#eef0ff",
        "secondary-fixed": "#6ffbbe",
        "surface-container-high": "#e2e7ff",
        "secondary": "#006c49",
        "surface-bright": "#faf8ff",
        "surface-dim": "#d2d9f4",
        "on-error": "#ffffff",
        "inverse-primary": "#c3c0ff",
        "tertiary-fixed-dim": "#ffb95f",
        "outline": "#777587",
        "on-primary-fixed": "#0f0069",
        "tertiary-fixed": "#ffddb8",
        "primary-container": "#4f46e5",
        "secondary-fixed-dim": "#4edea3"
      },
      borderRadius: {
        "DEFAULT": "0.25rem",
        "lg": "0.5rem",
        "xl": "0.75rem",
        "full": "9999px"
      },
      spacing: {
        "space-xs": "0.25rem",
        "space-sm": "0.5rem",
        "gutter": "1.5rem",
        "space-xl": "2.5rem",
        "space-md": "1rem",
        "space-lg": "1.5rem",
        "margin-mobile": "1rem",
        "gutter-mobile": "1rem",
        "margin": "2rem"
      },
      fontFamily: {
        "body-lg": inter,
        "display-hero": jakarta,
        "body-sm": inter,
        "headline-sm": jakarta,
        "label-sm": inter,
        "headline-md": jakarta,
        "label-md": inter,
        "display-hero-mobile": jakarta,
        "body-md": inter,
        "headline-lg-mobile": jakarta,
        "label-lg": inter,
        "headline-lg": jakarta,
        "code-tabular": inter,
      },
      fontSize: {
        "body-lg": [
          "16px",
          {
            "lineHeight": "26px",
            "letterSpacing": "-0.005em",
            "fontWeight": "400"
          }
        ],
        "display-hero": [
          "48px",
          {
            "lineHeight": "56px",
            "letterSpacing": "-0.03em",
            "fontWeight": "800"
          }
        ],
        "body-sm": [
          "12px",
          {
            "lineHeight": "18px",
            "letterSpacing": "0em",
            "fontWeight": "400"
          }
        ],
        "headline-sm": [
          "18px",
          {
            "lineHeight": "26px",
            "letterSpacing": "-0.01em",
            "fontWeight": "600"
          }
        ],
        "label-sm": [
          "11px",
          {
            "lineHeight": "14px",
            "letterSpacing": "0.04em",
            "fontWeight": "700"
          }
        ],
        "headline-md": [
          "24px",
          {
            "lineHeight": "32px",
            "letterSpacing": "-0.015em",
            "fontWeight": "600"
          }
        ],
        "label-md": [
          "12px",
          {
            "lineHeight": "16px",
            "letterSpacing": "0.02em",
            "fontWeight": "600"
          }
        ],
        "display-hero-mobile": [
          "32px",
          {
            "lineHeight": "40px",
            "letterSpacing": "-0.025em",
            "fontWeight": "800"
          }
        ],
        "body-md": [
          "14px",
          {
            "lineHeight": "22px",
            "letterSpacing": "0em",
            "fontWeight": "400"
          }
        ],
        "headline-lg-mobile": [
          "24px",
          {
            "lineHeight": "32px",
            "letterSpacing": "-0.02em",
            "fontWeight": "700"
          }
        ],
        "label-lg": [
          "14px",
          {
            "lineHeight": "20px",
            "letterSpacing": "0em",
            "fontWeight": "600"
          }
        ],
        "headline-lg": [
          "32px",
          {
            "lineHeight": "40px",
            "letterSpacing": "-0.02em",
            "fontWeight": "700"
          }
        ],
        "code-tabular": [
          "13px",
          {
            "lineHeight": "18px",
            "letterSpacing": "0.01em",
            "fontWeight": "500"
          }
        ]
      },
    },
  },
  plugins: [],
};
