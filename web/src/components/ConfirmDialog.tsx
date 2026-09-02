import { useEffect, useRef, type ReactNode } from "react";

interface ConfirmDialogProps {
  title: string;
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
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children && <div className="modal-body">{children}</div>}
        {error && (
          <div className="banner banner-danger" role="alert" style={{ marginTop: "var(--s-3)" }}>
            {error}
          </div>
        )}
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            ref={confirmRef}
            className={`btn ${confirmDanger ? "btn-danger" : "btn-primary"}`}
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
