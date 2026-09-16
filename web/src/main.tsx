import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { captureMailLink } from "./lib/mailLink";
import { applyThemeNow } from "./shell/theme";
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/shell.css";
import "./styles/components.css";
import "./styles/pages.css";

// Resolve light/dark before the first paint so the page never flashes.
applyThemeNow();

// Mailed password links arrive as `#/reset-password?token=…`. Translate the
// fragment into a route and take the token out of the URL before the router
// — or anything else — can see it.
captureMailLink();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
