const KNOWN = new Set(["draft", "finalized", "amended", "cancelled", "queued", "running", "complete", "failed"]);

/** Status chip. Unknown values (e.g. "v3") render as a neutral mono chip. */
export function StatusBadge({ status }: { status: string }) {
  if (KNOWN.has(status)) return <span className={`chip ${status}`}>{status}</span>;
  return <span className="chip version">{status}</span>;
}
