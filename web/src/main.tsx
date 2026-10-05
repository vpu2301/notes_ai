import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { captureMailLink } from "./lib/mailLink";
import { migrateStorageKeys } from "./lib/storageKeys";
import { applyThemeNow } from "./shell/theme";
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/shell.css";
import "./styles/components.css";
import "./styles/pages.css";

// Resolve light/dark before the first paint so the page never flashes.
applyThemeNow();

// Mailed links arrive as `#/reset-password?token=…`: take the token out of the URL before the router sees it.
captureMailLink();

// Values stored under the product's earlier name move to `notesai.*` once.
migrateStorageKeys();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
