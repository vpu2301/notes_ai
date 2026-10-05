import { useEffect } from "react";

const APP = "Notes AI";

/** Tab title "{what} — Notes AI"; restored on unmount so nothing inherits it. */
export function useDocumentTitle(what: string | null | undefined): void {
  useEffect(() => {
    const trimmed = (what ?? "").trim();
    document.title = trimmed ? `${trimmed} — ${APP}` : APP;
    return () => {
      document.title = APP;
    };
  }, [what]);
}
