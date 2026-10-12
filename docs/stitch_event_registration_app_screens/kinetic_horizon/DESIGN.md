---
name: Kinetic Horizon
colors:
  surface: '#faf8ff'
  surface-dim: '#d2d9f4'
  surface-bright: '#faf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3ff'
  surface-container: '#eaedff'
  surface-container-high: '#e2e7ff'
  surface-container-highest: '#dae2fd'
  on-surface: '#131b2e'
  on-surface-variant: '#464555'
  inverse-surface: '#283044'
  inverse-on-surface: '#eef0ff'
  outline: '#777587'
  outline-variant: '#c7c4d8'
  surface-tint: '#4d44e3'
  primary: '#3525cd'
  on-primary: '#ffffff'
  primary-container: '#4f46e5'
  on-primary-container: '#dad7ff'
  inverse-primary: '#c3c0ff'
  secondary: '#006c49'
  on-secondary: '#ffffff'
  secondary-container: '#6cf8bb'
  on-secondary-container: '#00714d'
  tertiary: '#684000'
  on-tertiary: '#ffffff'
  tertiary-container: '#885500'
  on-tertiary-container: '#ffd4a4'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e2dfff'
  primary-fixed-dim: '#c3c0ff'
  on-primary-fixed: '#0f0069'
  on-primary-fixed-variant: '#3323cc'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#faf8ff'
  on-background: '#131b2e'
  surface-variant: '#dae2fd'
typography:
  display-hero:
    fontFamily: Plus Jakarta Sans
    fontSize: 48px
    fontWeight: '800'
    lineHeight: 56px
    letterSpacing: -0.03em
  display-hero-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '800'
    lineHeight: 40px
    letterSpacing: -0.025em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  label-lg:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0em
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.04em
  code-tabular:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0.01em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  margin: 2rem
  gutter-mobile: 1rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system delivers a high-clarity, high-velocity operational environment for event managers and attendees alike. It balances professional administrative rigor with the excitement and immediacy of live events. The aesthetic aligns with **Modern Corporate / Minimalist Precision**, utilizing immaculate whitespace, confident typographic contrast, crisp boundary lines, and vibrant chromatic focal points.

### Personality & Demographics
- **Target Audience:** Event organizers, conference directors, enterprise operations teams, and live attendees accessing ticket passes and schedules.
- **Tone & Mood:** Efficient, poised, vibrant, frictionless. Interfaces feel responsive, clear, and reassuring during high-pressure check-in and launch operations.
- **Visual Tenets:**
  - *Operational Clarity:* Data density never compromises scannability; critical counts (capacity, revenue, check-in totals) are parsed in milliseconds.
  - *Tactile Signals:* Status is explicit and chromatic—green for live/confirmed, amber for capacity friction, rose for operational halts.
  - *Structural Restraint:* Subtle perimeter definitions keep dense views organized without visual noise.

## Colors

The palette establishes an unmistakable hierarchy built on high-contrast indigo action items, pristine surfaces, and semantic indicators.

### Core Roles
- **Primary (`#4F46E5` / `#6366F1`):** Deep Indigo to Electric Violet. Reserved for focal interaction points, active registration flows, confirmed progress states, and brand signatures. Never diluted with non-critical fills.
- **Secondary (`#10B981`):** Emerald. Signifies active admissions, successful check-ins, confirmed capacity, and completed transactions.
- **Tertiary / Warning (`#F59E0B`):** Amber. Denotes low-ticket thresholds, waitlist queues, pending verification, and capacity caps nearing exhaustion.
- **Critical / Destructive (`#EF4444`):** Rose Crimson. Signifies sold-out inventory, invalid badges, revoked access passes, and transactional declines.
- **Neutral Foundations:**
  - Canvas Baseline: `#F8FAFC` (Slate 50)
  - Card & Container Fill: `#FFFFFF` (White)
  - Perimeter Outlines: `#E2E8F0` (Slate 200)
  - Subdued / Secondary Typography: `#64748B` (Slate 500)
  - Primary Body & Subheadings: `#334155` (Slate 700)
  - High-Impact Headings & Display: `#0F172A` (Slate 900)

### Application Principles
- Use pure `#FFFFFF` for elevated foreground cards over the `#F8FAFC` canvas to naturally isolate modules without heavy shadows.
- Reserve `#4F46E5` for the single most important action per view (e.g., "Create Event", "Complete Registration", "Validate Scan").

## Typography

The typographic system combines the geometric dynamism of **Plus Jakarta Sans** for prominent headers with the legibility and systematic precision of **Inter** for dense dashboards, tickets, and forms.

### Rules & Guidelines
- **Tabular Figures:** Always apply `font-variant-numeric: tabular-nums` to ticket counters, order IDs, currency units, and capacity percentages to ensure stable grid alignment during live counter updates.
- **Visual Weighting:** Headers rely on heavy weights (600–800) with tight tracking to anchor dense data blocks. Micro-labels employ semibold uppercase styling with expanded letter spacing for rapid categorization.
- **Scale Restraint:** Display hero scales are restricted to marketing views and public registration landing pages. Administrative dashboards enforce a maximum header scale of `headline-lg` (`32px`).

## Layout & Spacing

The layout is grounded in a responsive 12-column fluid grid tailored for data monitoring, registration funnels, and attendee directories.

### Grid & Breakpoints
- **Desktop (≥ 1280px):** 12-column layout, 24px (`1.5rem`) gutters, 32px (`2rem`) margins. Max container constraint: `1440px`.
- **Tablet (768px – 1279px):** 8-column layout, 20px gutters, 24px margins. Stat cards reflow to 2x2 matrices; data tables introduce horizontal scroll boundaries with sticky lead identifiers.
- **Mobile (< 768px):** 4-column layout, 16px (`1rem`) gutters, 16px (`1rem`) margins. Complex modules break into single-column vertical stacks.

### Structural Flow
- Internal component rhythm follows an 8pt spatial baseline. Component padding consistently pairs `space-md` (`1rem`) with `space-lg` (`1.5rem`) to maintain breathable density in forms and modal dialogues.
- Section boundaries on administrative consoles leverage `space-xl` (`2.5rem`) separation to keep analytics, attendee queues, and configuration panels distinctly segregated.

## Elevation & Depth

Visual hierarchy uses a refined hybrid of **low-contrast outlines** and **diffused ambient shadows**. Interfaces remain crisp and clean without dark visual anchors.

### Elevation Hierarchy
- **Level 0 (Base Canvas):** `#F8FAFC`. Completely flat background plane.
- **Level 1 (Card & Module Layer):** `#FFFFFF` fill with a crisp perimeter rule (`1px solid #E2E8F0`) and an ambient glow: `0 1px 3px 0 rgba(15, 23, 42, 0.04), 0 1px 2px -1px rgba(15, 23, 42, 0.02)`.
- **Level 2 (Dropdowns & Popovers):** `#FFFFFF` fill, `1px solid #E2E8F0`, with elevated separation: `0 10px 15px -3px rgba(15, 23, 42, 0.08), 0 4px 6px -4px rgba(15, 23, 42, 0.04)`.
- **Level 3 (Modal Dialogs & Mobile Drawers):** `#FFFFFF` with an expanded reach: `0 20px 25px -5px rgba(15, 23, 42, 0.1), 0 8px 10px -6px rgba(15, 23, 42, 0.05)`, backed by a `#0F172A` backdrop mask at 45% opacity.

### Ambient Treatment
Shadows avoid pure black; they are tinted with slate neutral (`#0F172A`) to integrate naturally with typography and border rules.

## Shapes

The design system adopts a **Rounded** shape language (`roundedness: 2`), delivering an inviting, contemporary appearance while retaining the precision required for structured data interfaces.

### Corner Radius Mapping
- **Base (0.5rem / 8px):** Standard interactive primitives, including text inputs, standard buttons, select dropdowns, and tabular checkboxes.
- **Large (1rem / 16px):** Content cards, ticket summary boxes, metric stat modules, and interactive scan viewports.
- **Extra Large (1.5rem / 24px):** Modal panels, sheet drawers, and promotional registration hero banners.
- **Full Pill (`9999px`):** Reserved exclusively for status indicators, badge tags, filter chips, and circular icon triggers.

## Components

### Buttons
- **Primary:** `#4F46E5` fill, `#FFFFFF` text, `0.5rem` radius. Subtle hover shift to `#4338CA`. Active press: scale 0.98. Focus rings use `2px solid #6366F1` with an outer `2px` offset.
- **Secondary:** `#FFFFFF` fill, `1px solid #E2E8F0`, `#334155` label. Hover states apply `#F8FAFC` background and `#0F172A` text.
- **Destructive:** `#FEE2E2` fill, `#DC2626` text, transitioning on hover to `#EF4444` fill with `#FFFFFF` label.

### Status Chips & Badges
- Pill-shaped (`rounded-full`), `11px` to `12px` font size with semibold tracking (`label-sm`).
- **Confirmed / Live:** Emerald background (`#ECFDF5`), emerald text (`#047857`), optional 6px pulsing dot.
- **Low Stock / Waitlist:** Amber background (`#FEF3C7`), amber text (`#B45309`).
- **Sold Out / Error:** Rose background (`#FEF2F2`), rose text (`#B91C1C`).
- **Draft / Inactive:** Slate background (`#F1F5F9`), slate text (`#475569`).

### Input Fields
- White fill, `1px solid #CBD5E1` border, `0.5rem` radius, `0.625rem 0.875rem` padding.
- Focused state transitions border to `#4F46E5` with a `0 0 0 3px rgba(79, 70, 229, 0.15)` focus ring.
- Error states shift border to `#EF4444` with inline icon indicators and red error caption strings.

### Metric Stat Cards
- Enclosed white surface, `1px solid #E2E8F0` border, `1rem` radius, `space-lg` padding.
- Top row houses the title in `label-md` (`#64748B`) and a soft-tinted icon container.
- Main value features large tabular figures (`Plus Jakarta Sans`, 28px, bold).
- Bottom row displays positive/negative delta pill markers with secondary contextual text.

### Barcode & QR Code Ticket Modules
- Digital pass cards feature a distinct tear-line or dotted border delimiter separating event details from validation assets.
- QR code viewports are set on high-contrast `#FFFFFF` squares with high-contrast `#0F172A` framing to guarantee scan rates under variable lighting conditions.
- Ticket serial identifiers use `code-tabular` styling for clear manual fallback entry.

### Data Tables
- Clean horizontal divider architecture (`1px solid #F1F5F9`), omitting vertical column borders.
- Header row uses `#F8FAFC` background, `label-sm` uppercase text (`#64748B`), and consistent cell alignment.
- Rows feature subtle `#F8FAFC` hover states with optional right-aligned quick actions (e.g., "Check-In", "Resend Ticket").