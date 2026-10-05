import { useEffect } from "react";

const APP = "Notes AI";

/**
 * The browser tab's title for this screen: "{what} — Notes AI", or the
 * app name alone. Restored to the app name when the screen goes away, so
 * a page that sets nothing never inherits the previous one's.
 */
export function useDocumentTitle(what: string | null | undefined): void {
  useEffect(() => {
    const trimmed = (what ?? "").trim();
    document.title = trimmed ? `${trimmed} — ${APP}` : APP;
    return () => {
      document.title = APP;
    };
  }, [what]);
}
