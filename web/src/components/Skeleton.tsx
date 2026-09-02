import type { CSSProperties } from "react";

export function Skeleton({
  width,
  height = 14,
  style,
}: {
  width?: number | string;
  height?: number | string;
  style?: CSSProperties;
}) {
  return (
    <div
      className="skeleton"
      aria-hidden="true"
      style={{ width: width ?? "100%", height, ...style }}
    />
  );
}

export function SkeletonCard() {
  return (
    <div className="card note-card" aria-hidden="true">
      <div className="row1">
        <Skeleton width="40%" height={16} />
        <Skeleton width={70} height={20} style={{ borderRadius: 999 }} />
      </div>
      <Skeleton height={13} style={{ marginTop: 8 }} />
      <Skeleton width="65%" height={13} style={{ marginTop: 6 }} />
    </div>
  );
}
