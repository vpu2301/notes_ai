import { useCallback, useRef, useState, type ReactNode } from "react";
import { useDismiss } from "../lib/useDismiss";
import { CheckIcon, MoreIcon } from "./icons";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  /** Draw a separator above this item. */
  sep?: boolean;
  /** The current choice among options — a check at the end of the row. */
  checked?: boolean;
}

const MENU_W = 240;
const ITEM_H = 34;

/** An overflow ("⋯") menu: the home for actions that aren't the main path. */
export function Menu({
  items,
  label = "More actions",
  anchored = false,
  trigger,
  triggerClassName = "icon-btn",
}: {
  items: MenuItem[];
  label?: string;
  /** What the trigger shows; the ⋯ icon by default. */
  trigger?: ReactNode;
  triggerClassName?: string;
  /**
   * Position the panel `fixed` off the trigger instead of absolutely inside
   * it — needed wherever an ancestor clips overflow (a list panel, the
   * sidebar rail).
   */
  anchored?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  const btn = useRef<HTMLButtonElement>(null);

  const toggle = () => {
    if (!open && anchored && btn.current) {
      const r = btn.current.getBoundingClientRect();
      const height = items.length * ITEM_H + 10;
      const below = r.bottom + 6;
      setPos({
        left: Math.max(8, Math.min(r.right - MENU_W, window.innerWidth - MENU_W - 8)),
        top: below + height > window.innerHeight - 8 ? Math.max(8, r.top - height - 6) : below,
      });
    }
    setOpen((v) => !v);
  };

  const body = items.map((it) => (
    <div key={it.label}>
      {it.sep && <div className="menu-sep" />}
      <button
        className={`anchored-menu-item ${it.danger ? "danger" : ""}`}
        role={it.checked === undefined ? "menuitem" : "menuitemradio"}
        aria-checked={it.checked}
        disabled={it.disabled}
        onClick={() => {
          setOpen(false);
          it.onClick();
        }}
      >
        {it.icon}
        <span className="anchored-menu-label">{it.label}</span>
        {it.checked && <CheckIcon size={13} />}
      </button>
    </div>
  ));

  return (
    <div className="dropdown-host" ref={ref}>
      <button
        ref={btn}
        className={triggerClassName}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        {trigger ?? <MoreIcon />}
      </button>
      {open &&
        (anchored ? (
          pos && (
            <div className="anchored-menu" role="menu" aria-label={label} style={{ ...pos, minWidth: MENU_W }}>
              {body}
            </div>
          )
        ) : (
          <div className="dropdown" role="menu" aria-label={label}>
            {body}
          </div>
        ))}
    </div>
  );
}
