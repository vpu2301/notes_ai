import { useEffect, useRef, useState } from "react";
import { askNote } from "../api/notes";
import { errorMessage } from "../api/http";
import type { AskTurn } from "../api/types";
import { AlertIcon, ArrowUpIcon, SparkleIcon } from "./icons";
import { RichText } from "./RichText";

/**
 * "Ask this note" — the thread at the foot of the document and the
 * composer that floats over it, the same conversation the Mac app has.
 *
 * The thread lives here, not on the server: the client sends it back as
 * context with every question, so a follow-up has something to refer to.
 * It is dropped when the page is left — a question about a note is not a
 * record of anything, and nothing about it belongs in the note's history.
 */
export function AskNote({ noteId }: { noteId: string }) {
  const [thread, setThread] = useState<AskTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // A different note is a different conversation.
  useEffect(() => {
    setThread([]);
    setDraft("");
    setError(null);
  }, [noteId]);

  // Grow the composer with what is typed, up to the CSS max-height.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

  useEffect(() => {
    if (thread.length > 0 || asking) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [thread.length, asking]);

  const send = async () => {
    const question = draft.trim();
    if (!question || asking) return;
    const history = thread;
    setDraft("");
    setError(null);
    setThread([...history, { role: "user", text: question }]);
    setAsking(true);
    try {
      const res = await askNote(noteId, question, history);
      setThread((t) => [...t, { role: "assistant", text: res.answer }]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAsking(false);
    }
  };

  return (
    <>
      {(thread.length > 0 || asking || error) && (
        <div className="ask-thread" aria-live="polite">
          {thread.map((turn, i) =>
            turn.role === "user" ? (
              <div key={i} className="ask-turn you">
                <span>{turn.text}</span>
              </div>
            ) : (
              <div key={i} className="ask-turn ai">
                <span className="spark">
                  <SparkleIcon size={15} />
                </span>
                <RichText text={turn.text} />
              </div>
            ),
          )}
          {asking && (
            <div className="ask-turn ai">
              <span className="spark">
                <SparkleIcon size={15} />
              </span>
              <span className="ask-wait">
                Thinking
                <span className="dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
              </span>
            </div>
          )}
          {error && (
            <div className="banner banner-warn" role="alert">
              <AlertIcon size={15} />
              <span className="grow">{error}</span>
            </div>
          )}
          <div ref={endRef} />
        </div>
      )}

      <div className="ask-dock">
        <div className="ask-bar">
          <span className="spark">
            <SparkleIcon size={16} />
          </span>
          <textarea
            ref={inputRef}
            className="ask-input"
            rows={1}
            value={draft}
            placeholder="Ask about this note…"
            aria-label="Ask about this note"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Return sends; Shift+Return is a new line, as everywhere else.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button
            type="button"
            className="ask-send"
            aria-label="Send"
            title="Send (Return)"
            disabled={asking || draft.trim() === ""}
            onClick={() => void send()}
          >
            <ArrowUpIcon size={15} />
          </button>
        </div>
      </div>
    </>
  );
}
