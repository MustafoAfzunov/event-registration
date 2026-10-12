/** Material Symbols icon (the design's icon set). Decorative: hidden from assistive tech, so it
 * never leaks its ligature name ("search", "mail", …) into accessible names. */
export function Icon({
  name,
  filled = false,
  className = "",
}: {
  name: string;
  filled?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined select-none ${className}`}
      style={filled ? { fontVariationSettings: "'FILL' 1, 'wght' 400" } : undefined}
    >
      {name}
    </span>
  );
}
