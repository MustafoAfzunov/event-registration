import { useEffect } from "react";
import { Icon } from "./Icon";

/** Bottom-right confirmation toast (export: "Operational Toast"). Dismisses itself after 6 s. */
export function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 6000);
    return () => clearTimeout(id);
  }, [message, onDismiss]);
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-6 right-6 left-6 sm:left-auto z-[70] bg-inverse-surface text-inverse-on-surface px-4 py-3 rounded-xl shadow-xl flex items-center gap-3"
    >
      <Icon name="check_circle" filled className="text-secondary-fixed text-[20px] shrink-0" />
      <span className="font-body-sm text-body-sm">{message}</span>
      <button type="button" aria-label="Dismiss" onClick={onDismiss} className="ml-auto text-inverse-on-surface/70 hover:text-inverse-on-surface">
        <Icon name="close" className="text-[18px]" />
      </button>
    </div>
  );
}
