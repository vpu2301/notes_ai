import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
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
  disabled = false,
}: {
  items: MenuItem[];
  label?: string;
  /** What the trigger shows; the ⋯ icon by default. */
  trigger?: ReactNode;
  triggerClassName?: string;
  disabled?: boolean;
  /** `fixed` off the trigger, for ancestors that clip overflow. */
  anchored?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  const btn = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  const enabledItems = () =>
    Array.from(panel.current?.querySelectorAll<HTMLButtonElement>(".anchored-menu-item:not([disabled])") ?? []);

  // WAI-ARIA menu button: opens with the first item focused; arrows move, Escape closes.
  const shown = open && (!anchored || pos !== null);
  useEffect(() => {
    if (shown) enabledItems()[0]?.focus();
  }, [shown]);

  const closeToTrigger = () => {
    setOpen(false);
    btn.current?.focus();
  };

  const onMenuKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const list = enabledItems();
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const go = (i: number) => {
      e.preventDefault();
      list[(i + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at < 0 ? list.length - 1 : at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(list.length - 1);
    else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeToTrigger();
    } else if (e.key === "Tab") setOpen(false);
  };

  const toggle = () => {
    if (!open && anchored && btn.current) {
      const r = btn.current.getBoundingClientRect();
      const height = items.length * ITEM_H + 10;
      const below = r.bottom + 6;
      // A select aligns left; an overflow menu hangs off the right.
      const left = triggerClassName.startsWith("select-btn") ? r.left : r.right - MENU_W;
      setPos({
        left: Math.max(8, Math.min(left, window.innerWidth - MENU_W - 8)),
        top: below + height > window.innerHeight - 8 ? Math.max(8, r.top - height - 6) : below,
      });
    }
    setOpen((v) => !v);
  };

  const body = items.map((it) => (
    <div key={it.label}>
      {it.sep && <div className="menu-sep" />}
      <button
        type="button"
        className={`anchored-menu-item ${it.danger ? "danger" : ""}`}
        role={it.checked === undefined ? "menuitem" : "menuitemradio"}
        aria-checked={it.checked}
        disabled={it.disabled}
        tabIndex={-1}
        onClick={() => {
          closeToTrigger();
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
        type="button"
        ref={btn}
        className={triggerClassName}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && !open) {
            e.preventDefault();
            toggle();
          }
        }}
      >
        {trigger ?? <MoreIcon />}
      </button>
      {open &&
        (anchored ? (
          pos && (
            <div
              className="anchored-menu"
              role="menu"
              aria-label={label}
              ref={panel}
              onKeyDown={onMenuKey}
              style={{ ...pos, minWidth: MENU_W }}
            >
              {body}
            </div>
          )
        ) : (
          <div className="dropdown" role="menu" aria-label={label} ref={panel} onKeyDown={onMenuKey}>
            {body}
          </div>
        ))}
    </div>
  );
}
