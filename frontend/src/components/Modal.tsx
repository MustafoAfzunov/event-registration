import { useEffect, useId, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Dialog styled like the export's reschedule modal. Escape or a backdrop click closes it; focus moves
 * into the dialog, stays inside while open (Tab wraps) and returns to the opener on close. */
export function Modal({
  title,
  subtitle,
  icon,
  onClose,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  icon: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node?.querySelector<HTMLElement>("input, textarea, select")?.focus();
    if (node && !node.contains(document.activeElement)) node.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
      } else if (e.key === "Tab" && node) {
        const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)];
        const first = items[0];
        const last = items[items.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      opener?.focus?.();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-inverse-surface/40 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="bg-surface-container-lowest text-on-surface w-full max-w-xl max-h-[90vh] rounded-2xl shadow-xl flex flex-col overflow-hidden outline-none"
      >
        <div className="p-space-lg bg-surface-container-low flex items-center justify-between gap-space-md">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
              <Icon name={icon} className="text-[20px]" />
            </div>
            <div className="min-w-0">
              <h2 id={titleId} className="font-headline-sm text-headline-sm font-bold text-on-surface">{title}</h2>
              {subtitle && <p className="font-body-sm text-body-sm text-on-surface-variant">{subtitle}</p>}
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="w-8 h-8 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container transition-colors shrink-0"
          >
            <Icon name="close" className="text-[20px]" />
          </button>
        </div>
        <div className="p-space-lg flex flex-col gap-space-md overflow-y-auto">{children}</div>
        {footer && <div className="p-space-lg bg-surface-container-low flex items-center justify-end gap-space-sm">{footer}</div>}
      </div>
    </div>
  );
}
