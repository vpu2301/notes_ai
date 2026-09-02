import { useEffect, useRef, type ReactNode } from "react";
import { AlertIcon } from "./icons";

interface ConfirmDialogProps {
  title: string;
  /** one-line explainer under the title */
  subtitle?: string;
  children?: ReactNode;
  confirmLabel?: string;
  confirmDanger?: boolean;
  busy?: boolean;
  /** shown as a problem banner inside the dialog (e.g. validation detail) */
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  subtitle,
  children,
  confirmLabel = "Confirm",
  confirmDanger = false,
  busy = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-label={title}>
        <div className="modal-h">
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {(children || error) && (
          <div className="modal-b">
            {children}
            {error && (
              <div className="banner banner-danger" role="alert">
                <AlertIcon size={15} />
                <span className="grow">{error}</span>
              </div>
            )}
          </div>
        )}
        <div className="modal-f">
          <button className="btn ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            ref={confirmRef}
            className={`btn ${confirmDanger ? "danger" : "primary"}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
