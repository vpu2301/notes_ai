import { useCallback, useState, type ReactNode } from "react";
import { useDismiss } from "../lib/useDismiss";
import { MoreIcon } from "./icons";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  /** Draw a separator above this item. */
  sep?: boolean;
}

/** An overflow ("⋯") menu: the home for actions that aren't the main path. */
export function Menu({ items, label = "More actions" }: { items: MenuItem[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);

  return (
    <div className="dropdown-host" ref={ref}>
      <button
        className="icon-btn"
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <MoreIcon />
      </button>
      {open && (
        <div className="dropdown" role="menu" aria-label={label}>
          {items.map((it) => (
            <div key={it.label}>
              {it.sep && <div className="menu-sep" />}
              <button
                className={`anchored-menu-item ${it.danger ? "danger" : ""}`}
                role="menuitem"
                disabled={it.disabled}
                onClick={() => {
                  setOpen(false);
                  it.onClick();
                }}
              >
                {it.icon}
                <span className="anchored-menu-label">{it.label}</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
