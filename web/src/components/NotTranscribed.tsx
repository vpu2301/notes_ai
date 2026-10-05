import type { TranscriptCoverage } from "../api/types";
import { notTranscribed } from "../lib/coverageGaps";

/**
 * Sprint F1: the speech the transcript does not hold, named with its cause.
 * Each range opens the transcript at that moment; the time before the audio
 * started is not in the recording, so it is plain text. Nothing at all when
 * the whole recording was transcribed.
 */
export function NotTranscribed({
  coverage,
  onSeek,
}: {
  coverage: TranscriptCoverage | null | undefined;
  onSeek?: (ms: number) => void;
}) {
  const line = notTranscribed(coverage);
  if (!line) return null;
  return (
    <p className="help transcript-diagnostic" role="note">
      Not transcribed:{" "}
      {line.shown.map((item, i) => (
        <span key={`${item.startMs}-${i}`}>
          {i > 0 && ", "}
          {onSeek && item.seekable ? (
            <button type="button" className="link-btn" onClick={() => onSeek(item.startMs)}>
              {item.text}
            </button>
          ) : (
            item.text
          )}
        </span>
      ))}
      {line.more > 0 && ` +${line.more} more`}
    </p>
  );
}
