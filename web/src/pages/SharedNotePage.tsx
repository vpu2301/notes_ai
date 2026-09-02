import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/http";
import { downloadSharedPdf, getSharedNote } from "../api/notes";
import type { SharedNoteView } from "../api/types";
import { AlertIcon, DownloadIcon, FileDownIcon } from "../components/icons";
import { StatusBadge } from "../components/StatusBadge";
import { noteToMarkdown, safeFilename, saveBlob } from "../lib/exportNote";
import { formatDateTime } from "../lib/time";

/**
 * A note opened through a public link. Read-only, no sign-in, no shell:
 * the page an outsider sees when a colleague mails them the link.
 */
export function SharedNotePage() {
  const { token = "" } = useParams<{ token: string }>();
  const [note, setNote] = useState<SharedNoteView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    setNote(null);
    setError(null);
    getSharedNote(token)
      .then((n) => live && setNote(n))
      .catch((err) => live && setError(errorMessage(err)));
    return () => {
      live = false;
    };
  }, [token]);

  useEffect(() => {
    document.title = note ? `${note.title || "Untitled note"} — shared note` : "Shared note";
  }, [note]);

  const onPdf = async () => {
    if (!note) return;
    setBusy(true);
    try {
      saveBlob(await downloadSharedPdf(token), `${safeFilename(note.title, note.code)}.pdf`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onMarkdown = () => {
    if (!note) return;
    const md = noteToMarkdown({
      title: note.title,
      code: note.code,
      updatedAt: note.updated_at,
      sections: note.sections.map((s) => ({ name: s.name, text: s.text })),
    });
    saveBlob(new Blob([md], { type: "text/markdown;charset=utf-8" }), `${safeFilename(note.title, note.code)}.md`);
  };

  return (
    <div className="shared-shell">
      <header className="shared-bar">
        <span className="shared-brand">{note?.issuer_name ?? "Shared note"}</span>
        <span className="grow" />
        {note && (
          <>
            <button className="btn ghost sm" onClick={onMarkdown}>
              <FileDownIcon size={14} /> Markdown
            </button>
            <button className="btn sm" onClick={() => void onPdf()} disabled={busy}>
              <DownloadIcon size={14} /> PDF
            </button>
          </>
        )}
      </header>

      <main className="doc shared-doc">
        {error && (
          <div className="banner banner-danger" role="alert">
            <AlertIcon size={15} />
            <span className="grow">{error}</span>
          </div>
        )}
        {!note && !error && (
          <p className="help" aria-busy="true">
            Loading…
          </p>
        )}
        {note && (
          <>
            <h1 className="shared-title">{note.title || "Untitled note"}</h1>
            <div className="doc-meta">
              {note.status !== "draft" && <StatusBadge status={note.status} />}
              <span>Updated {formatDateTime(note.updated_at)}</span>
              <span className="sep">·</span>
              <span className="mono">{note.code}</span>
            </div>
            <div className="doc-body">
              {note.sections.length === 0 && <p className="help">This note is empty.</p>}
              {note.sections.map((s) => (
                <section key={s.section_key} className="doc-section">
                  <h2 className="section-name">{s.name}</h2>
                  <p className="shared-text">{s.text}</p>
                </section>
              ))}
            </div>
          </>
        )}
      </main>

      <footer className="shared-foot">
        Shared with a link. <Link to="/">Open Notes AI</Link>
      </footer>
    </div>
  );
}
