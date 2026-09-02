const KNOWN = new Set([
  "draft",
  "finalized",
  "amended",
  "cancelled",
  "queued",
  "running",
  "complete",
  "failed",
]);

export function StatusBadge({ status }: { status: string }) {
  const variant = KNOWN.has(status) ? status : "neutral";
  return <span className={`badge badge-${variant}`}>{status}</span>;
}
