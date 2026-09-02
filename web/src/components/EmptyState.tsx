import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  message,
  action,
  compact = false,
}: {
  icon: ReactNode;
  title: string;
  message: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty ${compact ? "compact" : ""}`}>
      <div className="empty-art" aria-hidden="true">
        {icon}
      </div>
      <h3>{title}</h3>
      <p>{message}</p>
      {action && <div className="empty-actions">{action}</div>}
    </div>
  );
}
