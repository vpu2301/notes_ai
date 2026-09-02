import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ToasterProvider } from "./components/Toaster";
import { LoginPage } from "./pages/LoginPage";
import { MeetingPage } from "./pages/MeetingPage";
import { NewNotePage } from "./pages/NewNotePage";
import { NoteEditorPage } from "./pages/NoteEditorPage";
import { NotesPage } from "./pages/NotesPage";
import { SharedNotePage } from "./pages/SharedNotePage";
import { AppShell } from "./shell/AppShell";

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
            <Route path="/login" element={<LoginPage />} />
            {/* Public link: anyone with the token, no sign-in. */}
            <Route path="/s/:token" element={<SharedNotePage />} />
            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route index element={<NotesPage />} />
              <Route path="/meeting/new" element={<MeetingPage />} />
              <Route path="/new" element={<NewNotePage />} />
              <Route path="/notes/:noteId" element={<NoteEditorPage />} />
              <Route path="/capture" element={<Navigate to="/meeting/new" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToasterProvider>
  );
}
