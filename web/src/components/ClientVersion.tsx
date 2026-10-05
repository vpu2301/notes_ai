import { useCallback, useEffect, useState } from "react";
import { messageFor } from "../lib/errorCopy";
import { getClientVersion, getClientVersionCheck } from "../api/notes";
import type { ClientVersion as ClientVersionData, ClientVersionCheck } from "../api/types";
import { RichText } from "./RichText";

/** Client version preview, built server-side by the same function as the shared page/PDF. */
export function ClientVersionPanel({ noteId }: { noteId: string }) {
  const [doc, setDoc] = useState<ClientVersionData | null>(null);
  const [check, setCheck] = useState<ClientVersionCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [version, warnings] = await Promise.all([
        getClientVersion(noteId),
        getClientVersionCheck(noteId).catch(() => null),
      ]);
      setDoc(version);
      setCheck(warnings);
      setError(null);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setLoading(false);
    }
  }, [noteId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="help">Building the client version…</p>;

  // 409 = this document type has no client version.
  if (error) {
    return (
      <div className="banner banner-info" role="status">
        {error}
      </div>
    );
  }
  if (!doc) return null;

  return (
    <div className="client-version">
      <p className="help">
        This is exactly what someone outside the workspace sees — on the shared page and in the
        PDF. Your own notes and the transcript are never part of it.
      </p>

      {check && check.warnings.length > 0 && (
        <ul className="client-warnings" aria-label="Worth checking before you share">
          {check.warnings.map((w) => (
            <li key={w.code}>
              <span className="client-warning-count">{w.count}</span> {w.detail}
            </li>
          ))}
        </ul>
      )}

      {doc.sections.length === 0 ? (
        <div className="banner banner-warn" role="status">
          There is nothing a client could read yet — every section is internal, empty, or the
          transcript.
        </div>
      ) : (
        <article className="client-doc">
          <h2 className="client-doc-title">{doc.title}</h2>
          {doc.sections.map((s) => (
            <section key={s.section_key}>
              {s.name && <h3>{s.name}</h3>}
              <RichText text={s.text} />
            </section>
          ))}
        </article>
      )}
    </div>
  );
}
