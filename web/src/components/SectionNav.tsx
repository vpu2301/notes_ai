import { useCallback, useEffect, useRef, useState } from "react";

export interface SectionNavItem {
  /** The section element's id (`sec-<key>`). */
  id: string;
  title: string;
}

// A section is "current" once its top passes this far below the top of the viewport.
const ACTIVE_OFFSET = 120;

/**
 * The note's sections as a column of short marks on the right edge; the current one is
 * darker. Hovering (or focusing) it opens the list of headings: hovering a heading tints
 * that section, clicking scrolls to it. Fewer than two headed sections: nothing.
 */
export function SectionNav({ items }: { items: SectionNavItem[] }) {
  const [active, setActive] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  // Rebuilt on every render of the page; read through a ref so scrolling is subscribed once.
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const ids = items.map((i) => i.id).join("|");

  const measure = useCallback(() => {
    const list = itemsRef.current;
    let current: string | null = list[0]?.id ?? null;
    for (const item of list) {
      const el = document.getElementById(item.id);
      if (el && el.getBoundingClientRect().top <= ACTIVE_OFFSET) current = item.id;
    }
    // At the end of the note the last sections cannot reach the top: the last one that
    // starts in the upper half of the window is current.
    const last = list.length ? document.getElementById(list[list.length - 1]!.id) : null;
    if (last && last.getBoundingClientRect().bottom <= window.innerHeight) {
      for (const item of list) {
        const top = document.getElementById(item.id)?.getBoundingClientRect().top;
        if (top !== undefined && top < window.innerHeight / 2) current = item.id;
      }
    }
    setActive(current);
  }, []);

  useEffect(() => {
    measure();
    // The page scrolls inside the shell, not the window: listen in the capture phase.
    document.addEventListener("scroll", measure, { capture: true, passive: true });
    window.addEventListener("resize", measure);
    return () => {
      document.removeEventListener("scroll", measure, { capture: true });
      window.removeEventListener("resize", measure);
    };
  }, [measure, ids]);

  const tint = (id: string, on: boolean) => document.getElementById(id)?.classList.toggle("nav-target", on);

  const go = (id: string) => {
    tint(id, false);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    setActive(id);
  };

  if (items.length < 2) return null;

  return (
    <nav
      className={`section-nav${open ? " open" : ""}`}
      aria-label="Sections of this note"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <div className="section-nav-rail" aria-hidden="true">
        {items.map((item) => (
          <span key={item.id} className={`section-nav-mark${item.id === active ? " on" : ""}`} />
        ))}
      </div>
      <ul className="section-nav-card">
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className={item.id === active ? "on" : undefined}
              aria-current={item.id === active ? "location" : undefined}
              onMouseEnter={() => tint(item.id, true)}
              onMouseLeave={() => tint(item.id, false)}
              onClick={() => go(item.id)}
            >
              {item.title}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
