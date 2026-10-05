import type { NameSuggestion } from "../api/types";
import { defaultSpeakerName } from "../api/types";
import { copyNodes, copyText } from "../i18n/speakers";
import { formatElapsed } from "../lib/time";
import { CloseIcon } from "./icons";

/** Name suggestion chip; the quote is always shown before anyone accepts. */
export function NameSuggestionChip({
  suggestion,
  speakerName,
  disabled = false,
  inline = false,
  onAccept,
  onDismiss,
  onShowQuote,
}: {
  suggestion: NameSuggestion;
  /** What the label is called right now ("Speaker 2"). */
  speakerName?: string;
  disabled?: boolean;
  /** Shown at the turn itself: the quote is plain text, there is nowhere to go. */
  inline?: boolean;
  onAccept: (s: NameSuggestion) => void;
  onDismiss: (s: NameSuggestion) => void;
  onShowQuote?: (s: NameSuggestion) => void;
}) {
  const speaker = speakerName ?? defaultSpeakerName(suggestion.label);
  const time = formatElapsed(suggestion.start_ms);
  const quote = copyText("suggestionQuote", { quote: suggestion.quote });
  return (
    <div
      className={`name-suggestion ${inline ? "inline" : ""}`}
      role="group"
      aria-label={copyText("suggestionGroup", { speaker })}
      data-suggestion-label={suggestion.label}
    >
      <span className="name-suggestion-text">
        {copyNodes("suggestionLead", { name: <strong>{suggestion.name}</strong> })}
        <span aria-hidden="true"> — </span>
        {onShowQuote && !inline ? (
          <button
            type="button"
            className="link-btn name-suggestion-quote"
            aria-label={copyText("suggestionQuoteLabel", { quote: suggestion.quote, time })}
            onClick={() => onShowQuote(suggestion)}
          >
            {quote}
          </button>
        ) : (
          <q className="name-suggestion-quote">{suggestion.quote}</q>
        )}
        <span aria-hidden="true"> · </span>
        <span className="name-suggestion-time mono">{time}</span>
      </span>
      <button
        type="button"
        className="btn sm"
        aria-label={copyText("suggestionAcceptLabel", { name: suggestion.name, speaker })}
        disabled={disabled}
        onClick={() => onAccept(suggestion)}
      >
        {copyText("suggestionAccept")}
      </button>
      <button
        type="button"
        className="icon-btn name-suggestion-dismiss"
        aria-label={copyText("suggestionDismiss")}
        title={copyText("suggestionDismiss")}
        disabled={disabled}
        onClick={() => onDismiss(suggestion)}
      >
        <CloseIcon size={12} />
      </button>
    </div>
  );
}
