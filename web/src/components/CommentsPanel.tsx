import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { addComment, deleteComment, editComment, listComments, setCommentResolved } from "../api/notes";
import type { CommentAnchorKind, NoteComment } from "../api/types";
import { messageFor } from "../lib/errorCopy";
import { relativeTime } from "../lib/time";
import { CloseIcon } from "./icons";

/** Bodies are plain text, at most this long (server rule). */
export const COMMENT_MAX = 2000;

export interface CommentAnchor {
  kind: CommentAnchorKind;
  /** null for the note as a whole. */
  key: string | null;
}

export const NOTE_ANCHOR: CommentAnchor = { kind: "note", key: null };

function anchorId(kind: string, key: string | null): string {
  return `${kind}:${key ?? ""}`;
}

/** The note's comments, read once when enabled and again on `reload`. */
export function useComments(noteId: string, enabled: boolean) {
  const [comments, setComments] = useState<NoteComment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setComments(await listComments(noteId));
      setError(null);
    } catch (err) {
      setError(messageFor(err));
    }
  }, [noteId]);

  useEffect(() => {
    if (!enabled) {
      setComments(null);
      return;
    }
    void reload();
  }, [enabled, reload]);

  return { comments, setComments, error, reload };
}

/**
 * Side panel: comments grouped by what they were left on, a compose box for the
 * chosen anchor, and every action only where the API's flags allow it.
 */
export function CommentsPanel({
  noteId,
  comments,
  error,
  onComments,
  canComment,
  anchor,
  onAnchor,
  labelFor,
  onJump,
  onClose,
}: {
  noteId: string;
  comments: NoteComment[] | null;
  error: string | null;
  onComments: (next: NoteComment[]) => void;
  /** The caller's level allows commenting; otherwise there is no compose box. */
  canComment: boolean;
  /** Where a new comment goes. */
  anchor: CommentAnchor;
  onAnchor: (anchor: CommentAnchor) => void;
  /** A section's title or an item line's text, for the group heading. */
  labelFor: (kind: CommentAnchorKind, key: string | null) => string;
  /** Scroll the note to what a comment is on. */
  onJump?: (kind: CommentAnchorKind, key: string) => void;
  onClose: () => void;
}) {
  const [showResolved, setShowResolved] = useState(false);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; body: string } | null>(null);

  const list = comments ?? [];
  const resolvedCount = list.filter((c) => c.resolved_at).length;
  const shown = showResolved ? list : list.filter((c) => !c.resolved_at);

  /** The note itself first, then each anchor in the order it was first commented on. */
  const groups = useMemo(() => {
    const out: { id: string; kind: CommentAnchorKind; key: string | null; present: boolean; items: NoteComment[] }[] = [];
    const sorted = [...shown].sort((a, b) => a.created_at.localeCompare(b.created_at));
    for (const c of sorted) {
      const id = anchorId(c.anchor_kind, c.anchor_key);
      const group = out.find((g) => g.id === id);
      if (group) group.items.push(c);
      else out.push({ id, kind: c.anchor_kind, key: c.anchor_key, present: c.anchor_present, items: [c] });
    }
    return out.sort((a, b) => Number(b.kind === "note") - Number(a.kind === "note"));
  }, [shown]);

  const replace = (next: NoteComment) => onComments(list.map((c) => (c.id === next.id ? next : c)));

  const act = async (work: () => Promise<void>) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch (err) {
      setProblem(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const post = (e: FormEvent) => {
    e.preventDefault();
    const text = body.trim();
    if (!text) return;
    void act(async () => {
      const created = await addComment(noteId, {
        anchor_kind: anchor.kind,
        anchor_key: anchor.key ?? undefined,
        body: text,
      });
      onComments([...list, created]);
      setBody("");
    });
  };

  const saveEdit = () => {
    if (!editing || !editing.body.trim()) return;
    const { id, body: text } = editing;
    void act(async () => {
      replace(await editComment(noteId, id, text.trim()));
      setEditing(null);
    });
  };

  const anchorLabel = anchor.kind === "note" ? "the whole note" : labelFor(anchor.kind, anchor.key);

  return (
    <aside className="panel comments-panel" aria-label="Comments">
      <div className="panel-h">
        <h3>Comments</h3>
        <span className="grow" />
        {resolvedCount > 0 && (
          <label className="help chk-row comments-resolved-toggle">
            <input
              type="checkbox"
              className="chk"
              checked={showResolved}
              onChange={(e) => setShowResolved(e.target.checked)}
            />
            Resolved ({resolvedCount})
          </label>
        )}
        <button className="icon-btn" aria-label="Close comments" onClick={onClose}>
          <CloseIcon size={13} />
        </button>
      </div>

      <div className="panel-b comments-body">
        {(error || problem) && (
          <div className="banner banner-danger" role="alert">
            <span className="grow">{problem ?? error}</span>
          </div>
        )}
        {comments === null && !error && <p className="help">Loading…</p>}
        {comments !== null && groups.length === 0 && (
          <p className="help">{canComment ? "No comments yet." : "No comments."}</p>
        )}

        {groups.map((g) => {
          const label = g.kind === "note" ? "On the note" : labelFor(g.kind, g.key);
          return (
            <section key={g.id} className="comment-group" aria-label={label}>
              <h4 className="comment-anchor">
                {g.kind !== "note" && g.present && onJump && g.key ? (
                  <button type="button" className="link-btn" onClick={() => onJump(g.kind, g.key as string)}>
                    {label}
                  </button>
                ) : (
                  <span>{label}</span>
                )}
                {g.kind !== "note" && !g.present && <span className="chip comment-removed">on a removed line</span>}
              </h4>
              {g.items.map((c) => (
                <article key={c.id} className={`comment ${c.resolved_at ? "resolved" : ""}`}>
                  <div className="comment-h">
                    <span className="comment-author">{c.author.display_name}</span>
                    <span className="help">
                      {relativeTime(c.created_at)}
                      {c.edited_at && " · edited"}
                    </span>
                  </div>
                  {editing?.id === c.id ? (
                    <div className="comment-edit">
                      <textarea
                        className="textarea"
                        rows={3}
                        aria-label="Edit comment"
                        maxLength={COMMENT_MAX}
                        value={editing.body}
                        disabled={busy}
                        onChange={(e) => setEditing({ id: c.id, body: e.target.value })}
                      />
                      <div className="comment-actions">
                        <button className="btn sm" disabled={busy || !editing.body.trim()} onClick={saveEdit}>
                          Save
                        </button>
                        <button className="btn ghost sm" disabled={busy} onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="comment-text">{c.body}</p>
                  )}
                  {c.resolved_at && (
                    <p className="help">Resolved{c.resolved_by_display ? ` by ${c.resolved_by_display}` : ""}</p>
                  )}
                  {editing?.id !== c.id && (c.can_edit || c.can_resolve || c.can_delete) && (
                    <div className="comment-actions">
                      {c.can_edit && (
                        <button className="btn ghost sm" disabled={busy} onClick={() => setEditing({ id: c.id, body: c.body })}>
                          Edit
                        </button>
                      )}
                      {c.can_resolve && (
                        <button
                          className="btn ghost sm"
                          disabled={busy}
                          onClick={() => void act(async () => replace(await setCommentResolved(noteId, c.id, !c.resolved_at)))}
                        >
                          {c.resolved_at ? "Reopen" : "Resolve"}
                        </button>
                      )}
                      {c.can_delete && (
                        <button
                          className="btn ghost sm danger-text"
                          disabled={busy}
                          onClick={() =>
                            void act(async () => {
                              await deleteComment(noteId, c.id);
                              onComments(list.filter((x) => x.id !== c.id));
                            })
                          }
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  )}
                </article>
              ))}
            </section>
          );
        })}

        {canComment && (
          <form className="comment-compose" onSubmit={post}>
            <span className="help comment-target">
              On {anchorLabel}
              {anchor.kind !== "note" && (
                <button
                  type="button"
                  className="icon-btn"
                  aria-label="Comment on the whole note instead"
                  title="Comment on the whole note instead"
                  onClick={() => onAnchor(NOTE_ANCHOR)}
                >
                  <CloseIcon size={11} />
                </button>
              )}
            </span>
            <textarea
              className="textarea"
              rows={3}
              aria-label="Comment"
              placeholder="Add a comment"
              maxLength={COMMENT_MAX}
              value={body}
              disabled={busy}
              onChange={(e) => setBody(e.target.value)}
            />
            <button className="btn moss sm" type="submit" disabled={busy || !body.trim()}>
              Comment
            </button>
          </form>
        )}
      </div>
    </aside>
  );
}
