// Class-name building blocks taken from the Stitch export's components (DESIGN.md "Components").
// Full literal class strings only: Tailwind finds classes by scanning source text.

export const pageX = "px-margin-mobile md:px-margin";
export const pageContainer = `w-full max-w-7xl mx-auto ${pageX} py-space-lg`;
export const adminContainer = `w-full max-w-[1440px] mx-auto ${pageX} py-space-lg`;

export const card = "bg-surface-container-lowest rounded-xl shadow-sm";
export const labelSm = "font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider";

const btn =
  "inline-flex items-center justify-center gap-2 rounded-lg font-label-lg text-label-lg transition-all active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed disabled:active:scale-100";
/** Primary: indigo fill. One per view (DESIGN.md). */
export const btnPrimary = `${btn} bg-primary text-on-primary hover:bg-primary-container shadow-md px-space-md py-2.5`;
/** Secondary: white fill, 1px outline. */
export const btnSecondary = `${btn} bg-surface-container-lowest text-on-surface border border-outline-variant hover:bg-surface hover:text-on-surface px-space-md py-2.5`;
/** Soft: tonal button used for the dashboard's header actions. */
export const btnSoft = `${btn} bg-surface-container-high text-on-surface hover:bg-surface-container-highest shadow-sm px-4 py-2.5`;
/** Destructive: rose tint that turns solid on hover. */
export const btnDanger = `${btn} bg-error-container text-error hover:bg-error hover:text-on-error px-space-md py-2.5`;
/** Waitlist action (amber), used instead of primary when the event is full. */
export const btnWarn = `${btn} bg-tertiary-container text-on-tertiary hover:bg-tertiary shadow-md px-space-md py-3`;

export const input =
  "w-full rounded-lg bg-surface border border-outline-variant text-on-surface font-body-md text-body-md px-3 py-2 placeholder:text-outline focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20";
export const label = "block font-label-md text-label-md text-on-surface mb-1";
