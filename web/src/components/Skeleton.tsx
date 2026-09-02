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
  return <div className="skeleton" aria-hidden="true" style={{ width: width ?? "100%", height, ...style }} />;
}

/** A placeholder list row with the same shape as a note row. */
export function SkeletonRow() {
  return (
    <div className="row" aria-hidden="true">
      <Skeleton width={32} height={32} style={{ borderRadius: 9 }} />
      <div className="row-body">
        <div className="row-1">
          <Skeleton width="38%" height={14} />
          <Skeleton width={60} height={18} style={{ borderRadius: 99 }} />
        </div>
        <Skeleton width="70%" height={12} style={{ marginTop: 8 }} />
      </div>
      <Skeleton width={64} height={12} />
    </div>
  );
}
