import { useCallback, useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";

const KEY = "notesai.theme";

/**
 * The web is white by default — the paper-and-ink look of the Mac app on a
 * pure white ground — whatever the OS appearance says. Dark and "follow the
 * system" stay one click away in the sidebar and are remembered once chosen.
 */
const DEFAULT_PREF: ThemePref = "light";

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_PREF;
}

function systemDark(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

/**
 * Stamps a CONCRETE light/dark onto <html data-theme> before first paint.
 * Every dark rule in the stylesheets is `[data-theme="dark"]`, so resolving
 * "system" here is what lets the whole cascade stay flat.
 */
export function applyThemeNow() {
  const pref = readPref();
  const resolved = pref === "system" ? (systemDark() ? "dark" : "light") : pref;
  document.documentElement.dataset.theme = resolved;
}

/** Theme preference + resolved value; "system" keeps following the OS. */
export function useTheme() {
  const [pref, setPrefState] = useState<ThemePref>(readPref);
  const [osDark, setOsDark] = useState(systemDark);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setOsDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const resolved: "light" | "dark" = pref === "system" ? (osDark ? "dark" : "light") : pref;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const setPref = useCallback((next: ThemePref) => {
    setPrefState(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  return { pref, resolved, setPref };
}
