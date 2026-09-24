import { useEffect, useMemo, useState } from "react";
import { getGeneratedItems } from "../api/generation";
import type { GeneratedItem } from "../api/types";

/**
 * The rows behind a generated note, by line key (Summary Engine v2, Q5).
 * Loaded once per note version — a note has well under 200 lines, so one
 * request is the whole cost. Empty for a note nobody generated, and for
 * rows written before Q5: those lines simply have no evidence to open.
 */
export function useGeneratedLines(noteId: string, version: number | null) {
  const [rows, setRows] = useState<GeneratedItem[]>([]);
  useEffect(() => {
    let alive = true;
    getGeneratedItems(noteId, { generation: "current" })
      .then((items) => alive && setRows(items))
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [noteId, version]);
  const byKey = useMemo(() => new Map(rows.map((r) => [r.item_key, r])), [rows]);
  return { rows, byKey };
}
