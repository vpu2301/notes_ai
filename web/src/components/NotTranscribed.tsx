import type { TranscriptCoverage } from "../api/types";
import { notTranscribed } from "../lib/coverageGaps";

/** Untranscribed ranges with their cause; time before the audio started is not seekable. */
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
