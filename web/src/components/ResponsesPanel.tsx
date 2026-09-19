import { useState } from "react";
import { errorMessage } from "../api/http";
import { clearResponse, setItemStatus } from "../api/notes";
import type { ItemView, ResponseView, TemplateSection } from "../api/types";
import { useToast } from "./Toaster";

/**
 * The author's view of what recipients did (Sprint 20). Counts per item,
 * every dispute with its comment and who sent it, "Mark done" and "Clear".
 * Comments are recipient-authored: they go through React text nodes and
 * nothing else — never markup.
 */
export function ResponsesPanel({
  noteId,
  items,
  responses,
  sections,
  onItems,
  onResponses,
}: {
  noteId: string;
  items: ItemView[];
  responses: ResponseView[];
  sections: TemplateSection[];
  onItems: (items: ItemView[]) => void;
  onResponses: (responses: ResponseView[]) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  const markDone = async (item: ItemView) => {
    setBusy(item.id);
    try {
      const next = await setItemStatus(noteId, item.id, item.status === "done" ? "open" : "done");
      onItems(items.map((i) => (i.id === item.id ? next : i)));
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const clear = async (r: ResponseView) => {
    setBusy(r.id);
    try {
      await clearResponse(noteId, r.id);
      onResponses(responses.filter((x) => x.id !== r.id));
      onItems(
        items.map((i) =>
          i.item_key === r.item_key
            ? {
                ...i,
                responses: i.responses.filter((x) => x.id !== r.id),
                counts: {
                  confirms: i.counts.confirms - (r.kind === "confirm" ? 1 : 0),
                  dones: i.counts.dones - (r.kind === "done" ? 1 : 0),
                  disputes: i.counts.disputes - (r.kind === "dispute" ? 1 : 0),
                },
              }
            : i,
        ),
      );
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const flags = responses.filter((r) => r.kind === "flag");
  const sectionName = (key: string | null) => sections.find((s) => s.id === key)?.name ?? key ?? "";

  const summary = (i: ItemView) => {
    const parts: string[] = [];
    if (i.counts.confirms) parts.push(`${i.counts.confirms} confirmed`);
    if (i.counts.dones) parts.push(`${i.counts.dones} done`);
    if (i.counts.disputes) parts.push(`${i.counts.disputes} disputed`);
    return parts.length ? parts.join(" · ") : "No responses yet";
  };

  return (
    <div className="doc-body responses-panel" aria-label="Responses">
      {items.length === 0 && <p className="help">No action items on this note yet. Lines in the “Action items” section become items automatically.</p>}
      {items.map((item) => (
        <section key={item.id} className={`doc-section response-item state-${item.status}`}>
          <div className="response-item-head">
            <span className="shared-item-glyph" aria-hidden="true">
              {item.status === "done" ? "☑" : "☐"}
            </span>
            <div className="grow">
              <div className="response-item-text">{item.text}</div>
              <div className="response-item-meta">
                {item.owner_label && (
                  <span className="chip owner" title={item.owner_confidence !== null && item.owner_confidence < 1 ? "Owner inferred — check it" : undefined}>
                    {item.owner_label}
                    {item.owner_confidence !== null && item.owner_confidence < 1 && " · check owner"}
                  </span>
                )}
                {(item.due_date || item.due_text) && <span className="chip due">{item.due_date ?? item.due_text}</span>}
                <span className="help">{summary(item)}</span>
              </div>
            </div>
            <button className="btn sm" disabled={busy === item.id} onClick={() => void markDone(item)}>
              {item.status === "done" ? "Reopen" : "Mark done"}
            </button>
          </div>
          {item.responses.length > 0 && (
            <ul className="response-list">
              {item.responses.map((r) => (
                <li key={r.id} className={`response kind-${r.kind}`}>
                  <span className="chip version">{r.kind}</span>
                  <span className="row-name">{r.link_label || "A recipient"}</span>
                  {r.comment && <p className="response-comment">{r.comment}</p>}
                  <button className="btn ghost sm" disabled={busy === r.id} onClick={() => void clear(r)}>
                    Clear
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
      {flags.length > 0 && (
        <section className="doc-section">
          <h2 className="section-name">Flagged sections</h2>
          <ul className="response-list">
            {flags.map((r) => (
              <li key={r.id} className="response kind-flag">
                <span className="chip cancelled">{sectionName(r.section_key)}</span>
                <span className="row-name">{r.link_label || "A recipient"}</span>
                {r.comment && <p className="response-comment">{r.comment}</p>}
                <button className="btn ghost sm" disabled={busy === r.id} onClick={() => void clear(r)}>
                  Clear
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
