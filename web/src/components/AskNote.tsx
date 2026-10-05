import { useEffect, useRef, useState } from "react";
import { askNote } from "../api/notes";
import { messageFor } from "../lib/errorCopy";
import type { AskTurn } from "../api/types";
import { AlertIcon, ArrowUpIcon, SparkleIcon } from "./icons";
import { RichText } from "./RichText";

/** "Ask this note": the thread is client-only and sent back as context with each question. */
export function AskNote({
  noteId,
  resetKey = 0,
  onThreadChange,
}: {
  noteId: string;
  /** Bump to clear the thread (the ⋯ menu's "Clear chat"). */
  resetKey?: number;
  onThreadChange?: (count: number) => void;
}) {
  const [thread, setThread] = useState<AskTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setThread([]);
    setDraft("");
    setError(null);
  }, [noteId]);

  useEffect(() => {
    if (resetKey > 0) {
      setThread([]);
      setError(null);
    }
  }, [resetKey]);

  useEffect(() => {
    onThreadChange?.(thread.length);
  }, [thread.length, onThreadChange]);

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
      setError(messageFor(err));
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
              <div key={`${i}-you`} className="ask-turn you">
                <span>{turn.text}</span>
              </div>
            ) : (
              <div key={`${i}-ai`} className="ask-turn ai">
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
        <div className="ask-bar" onClick={() => inputRef.current?.focus()}>
          <textarea
            ref={inputRef}
            className="ask-input"
            rows={1}
            value={draft}
            placeholder="Ask about this note…"
            aria-label="Ask about this note"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <div className="ask-tools">
            <span className="ask-scope">
              <SparkleIcon size={14} />
              This note
            </span>
            <button
              type="button"
              className="ask-send"
              aria-label="Send"
              title="Send (Return)"
              disabled={asking || draft.trim() === ""}
              onClick={(e) => {
                e.stopPropagation();
                void send();
              }}
            >
              <ArrowUpIcon size={16} />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
