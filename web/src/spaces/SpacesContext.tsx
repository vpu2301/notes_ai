// The user's spaces, loaded once for the whole shell: the sidebar lists
// them, the notes list filters by one, the note's ⋯ menu files into one.
// Writes are optimistic and fall back to a reload when the server says no,
// the same way the Mac app handles them.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { errorMessage } from "../api/http";
import * as spacesApi from "../api/spaces";
import type { Space } from "../api/types";
import { useToast } from "../components/Toaster";

interface SpacesValue {
  spaces: Space[];
  /** note id → space id, derived from `spaces`. */
  spaceOf: Record<string, string>;
  loading: boolean;
  /** The initial load failed; writes report themselves as a toast. */
  error: string | null;
  refresh: () => Promise<void>;
  create: (name: string) => Promise<Space | null>;
  rename: (id: string, name: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  /** File the note in a space; `null` takes it out of its space. */
  file: (noteId: string, spaceId: string | null) => Promise<void>;
  /** The note is gone — drop it from every space. */
  forgetNote: (noteId: string) => void;
}

const SpacesContext = createContext<SpacesValue | null>(null);

export function useSpaces(): SpacesValue {
  const ctx = useContext(SpacesContext);
  if (!ctx) throw new Error("useSpaces must be used inside <SpacesProvider>");
  return ctx;
}

export function SpacesProvider({ children }: { children: ReactNode }) {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    try {
      setSpaces(await spacesApi.listSpaces());
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const spaceOf = useMemo(() => {
    const map: Record<string, string> = {};
    for (const space of spaces) {
      for (const noteId of space.note_ids) map[noteId] = space.id;
    }
    return map;
  }, [spaces]);

  const create = useCallback(
    async (name: string): Promise<Space | null> => {
      const trimmed = name.trim();
      if (!trimmed) return null;
      try {
        const space = await spacesApi.createSpace(trimmed);
        setSpaces((prev) => [...prev, space]);
        return space;
      } catch (err) {
        toast.error(errorMessage(err));
        return null;
      }
    },
    [toast],
  );

  const rename = useCallback(
    async (id: string, name: string) => {
      const trimmed = name.trim();
      if (!trimmed) return;
      setSpaces((prev) => prev.map((s) => (s.id === id ? { ...s, name: trimmed } : s)));
      try {
        await spacesApi.renameSpace(id, trimmed);
      } catch (err) {
        toast.error(errorMessage(err));
        await refresh();
      }
    },
    [refresh, toast],
  );

  const remove = useCallback(
    async (id: string) => {
      setSpaces((prev) => prev.filter((s) => s.id !== id));
      try {
        await spacesApi.deleteSpace(id);
      } catch (err) {
        toast.error(errorMessage(err));
        await refresh();
      }
    },
    [refresh, toast],
  );

  const file = useCallback(
    async (noteId: string, spaceId: string | null) => {
      setSpaces((prev) =>
        prev.map((s) => {
          const without = s.note_ids.filter((id) => id !== noteId);
          return { ...s, note_ids: s.id === spaceId ? [...without, noteId] : without };
        }),
      );
      try {
        await spacesApi.fileNote(noteId, spaceId);
      } catch (err) {
        toast.error(errorMessage(err));
        await refresh();
      }
    },
    [refresh, toast],
  );

  const forgetNote = useCallback((noteId: string) => {
    setSpaces((prev) => prev.map((s) => ({ ...s, note_ids: s.note_ids.filter((id) => id !== noteId) })));
  }, []);

  const value = useMemo<SpacesValue>(
    () => ({ spaces, spaceOf, loading, error, refresh, create, rename, remove, file, forgetNote }),
    [spaces, spaceOf, loading, error, refresh, create, rename, remove, file, forgetNote],
  );

  return <SpacesContext.Provider value={value}>{children}</SpacesContext.Provider>;
}
