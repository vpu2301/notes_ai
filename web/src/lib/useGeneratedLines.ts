import { useEffect, useMemo, useState } from "react";
import { getGeneratedItems } from "../api/generation";
import type { GeneratedItem } from "../api/types";

/** Evidence rows behind a generated note, by line key; one request per note version. */
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
