import { api } from "./http";
import type { FeedPage, ReadResult, UnreadCount } from "./types";

export function unreadCount(): Promise<UnreadCount> {
  return api<UnreadCount>("notification", "/v1/notifications/unread-count");
}

export function feed(limit = 15): Promise<FeedPage> {
  return api<FeedPage>("notification", "/v1/notifications", { query: { limit } });
}

export function markRead(id: string): Promise<ReadResult> {
  return api<ReadResult>("notification", `/v1/notifications/${id}/read`, {
    method: "POST",
  });
}

export function markAllRead(): Promise<ReadResult> {
  return api<ReadResult>("notification", "/v1/notifications/read-all", {
    method: "POST",
  });
}
