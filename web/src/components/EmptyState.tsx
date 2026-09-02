import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  message,
  action,
}: {
  icon: ReactNode;
  title: string;
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-art" aria-hidden="true">
        {icon}
      </div>
      <h3>{title}</h3>
      <p>{message}</p>
      {action}
    </div>
  );
}
