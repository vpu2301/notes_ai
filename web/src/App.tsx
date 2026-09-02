import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ToasterProvider } from "./components/Toaster";
import { CapturePage } from "./pages/CapturePage";
import { LoginPage } from "./pages/LoginPage";
import { NewNotePage } from "./pages/NewNotePage";
import { NoteEditorPage } from "./pages/NoteEditorPage";
import { NotesPage } from "./pages/NotesPage";
import { AppShell } from "./shell/AppShell";

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "restoring") {
    // A quiet splash: the silent-refresh either restores the session in a
    // few hundred ms or lands the user on /login — no flash of either UI.
    return (
      <div className="login-wrap" aria-busy="true">
        <div className="save-state saving">
          <span className="sdot" /> Signing you in…
        </div>
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
            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route index element={<NotesPage />} />
              <Route path="/new" element={<NewNotePage />} />
              <Route path="/notes/:noteId" element={<NoteEditorPage />} />
              <Route path="/capture" element={<CapturePage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToasterProvider>
  );
}
