/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** auth-service base URL (dev default http://localhost:8000; required in a production build) */
  readonly VITE_AUTH_BASE?: string;
  /** asr-service base URL (dev default http://localhost:8001; required in a production build) */
  readonly VITE_ASR_BASE?: string;
  /** notification-service base URL (dev default http://localhost:8004; required in a production build) */
  readonly VITE_NOTIFICATION_BASE?: string;
  /** note-service base URL (dev default http://localhost:8006; required in a production build) */
  readonly VITE_NOTE_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
