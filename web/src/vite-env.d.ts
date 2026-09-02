/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** auth-service base URL (default http://localhost:8000) */
  readonly VITE_AUTH_BASE?: string;
  /** asr-service base URL (default http://localhost:8001) */
  readonly VITE_ASR_BASE?: string;
  /** notification-service base URL (default http://localhost:8004) */
  readonly VITE_NOTIFICATION_BASE?: string;
  /** note-service base URL (default http://localhost:8006) */
  readonly VITE_NOTE_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
