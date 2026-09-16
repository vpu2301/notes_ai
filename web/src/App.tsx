import { Fragment, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ToasterProvider } from "./components/Toaster";
import { LoginPage } from "./pages/LoginPage";
import { AccountRecoveryPage } from "./pages/auth/AccountRecoveryPage";
import { MfaPage } from "./pages/auth/MfaPage";
import { PasswordLoginPage } from "./pages/auth/PasswordLoginPage";
import { ResetPasswordPage } from "./pages/auth/ResetPasswordPage";
import { SignupPage } from "./pages/auth/SignupPage";
import { WelcomePage } from "./pages/auth/WelcomePage";
import { ReauthDialog } from "./components/ReauthDialog";
import { AccountSettingsPage } from "./pages/settings/AccountSettingsPage";
import { DevicesSettingsPage } from "./pages/settings/DevicesSettingsPage";
import { SecuritySettingsPage } from "./pages/settings/SecuritySettingsPage";
import { SettingsLayout } from "./pages/settings/SettingsLayout";
import { MeetingPage } from "./pages/MeetingPage";
import { NewNotePage } from "./pages/NewNotePage";
import { NoteEditorPage } from "./pages/NoteEditorPage";
import { NotesPage } from "./pages/NotesPage";
import { SharedNotePage } from "./pages/SharedNotePage";
import { AppShell } from "./shell/AppShell";
import { SpacesProvider } from "./spaces/SpacesContext";

/**
 * The signed-in half of the app, remounted whenever the active workspace
 * changes.
 *
 * Every page here fetches through `api()` into local state — there is no
 * query cache to invalidate — so the only honest way to re-scope the UI is
 * to throw the old tree away. The key covers `SpacesProvider`'s cache and
 * `NotificationBell`'s poll along with every page.
 *
 * It is inert today: nothing can change `activeTenantId` yet, because
 * `POST /auth/token` (the workspace-scoped token exchange) does not exist —
 * see `docs/sprints/IDX-W2.md`. It is here so that the switcher, when B1/A2
 * land, is a list and a call rather than a hunt for stale state.
 */
function WorkspaceScope({ children }: { children: ReactNode }) {
  const { activeTenantId } = useAuth();
  return <Fragment key={activeTenantId ?? "no-workspace"}>{children}</Fragment>;
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "restoring") {
    // A quiet splash: the silent-refresh either restores the session in a
    // few hundred ms or lands the user on /login — no flash of either UI.
    return (
      <div className="splash dotted" aria-busy="true">
        <span className="save-status" data-state="saving">
          <span className="dot" /> Signing you in…
        </span>
      </div>
    );
  }
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export function App() {
  return (
    <ToasterProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Signed-out flows. `/welcome` is the exception — it needs the
                session the code step just created, and guards itself. */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/login/password" element={<PasswordLoginPage />} />
            <Route path="/login/mfa" element={<MfaPage />} />
            {/* Self-serve account creation (BE-0). Also the route macOS and
                iOS open in a browser from "Create one". */}
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/reset" element={<ResetPasswordPage />} />
            <Route path="/account-recovery" element={<AccountRecoveryPage />} />
            <Route path="/welcome" element={<WelcomePage />} />
            {/* Public link: anyone with the token, no sign-in. */}
            <Route path="/s/:token" element={<SharedNotePage />} />
            <Route
              element={
                <RequireAuth>
                  <WorkspaceScope>
                    <SpacesProvider>
                      <AppShell />
                    </SpacesProvider>
                  </WorkspaceScope>
                </RequireAuth>
              }
            >
              <Route index element={<NotesPage />} />
              <Route path="/spaces/:spaceId" element={<NotesPage />} />
              <Route path="/meeting/new" element={<MeetingPage />} />
              <Route path="/new" element={<NewNotePage />} />
              <Route path="/notes/:noteId" element={<NoteEditorPage />} />
              <Route path="/capture" element={<Navigate to="/meeting/new" replace />} />
              <Route path="/settings" element={<SettingsLayout />}>
                <Route index element={<Navigate to="/settings/account" replace />} />
                <Route path="account" element={<AccountSettingsPage />} />
                <Route path="security" element={<SecuritySettingsPage />} />
                {/* Server-checked as well — see DevicesSettingsPage. */}
                <Route path="devices" element={<DevicesSettingsPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          {/* The one step-up prompt, mounted above every route so that a
              403 raised anywhere resolves in the same place. */}
          <ReauthDialog />
        </BrowserRouter>
      </AuthProvider>
    </ToasterProvider>
  );
}
