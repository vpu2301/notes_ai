import { useEffect } from "react";
import { LoginShell } from "./auth/LoginShell";

/**
 * `/s/privacy` — what a shared page collects and who controls it (Sprint 23).
 * Static, no session, no calls. Reviewed copy lives here and nowhere else.
 */
export function SharedPrivacyPage() {
  useEffect(() => {
    document.title = "Privacy — shared notes";
  }, []);
  return (
    <LoginShell title="Privacy for shared notes">
      <div className="doc-body shared-privacy">
        <h2 className="section-name">What this page collects</h2>
        <p>
          When you open a shared note we record that the link was opened and when. If you confirm, complete,
          dispute or flag something, that action and any comment you type are stored with the link you used.
          If the workspace asks you to verify by code, the address the link was sent to is used once to deliver
          the code. Nothing else about you is collected, and no cookies are set on this page.
        </p>
        <h2 className="section-name">Who controls it</h2>
        <p>
          The workspace that shared the note controls this data. Its name is shown at the top of the page, and
          replies to any e-mail from it go to the person who shared. We process the data on that workspace's behalf.
        </p>
        <h2 className="section-name">How long it is kept</h2>
        <p>
          Links expire on a date the sender chose (shown at the bottom of the page). Thirty days after a link
          expires, your responses are cleared and your address is removed from it.
        </p>
        <h2 className="section-name">Your choices</h2>
        <p>
          Every e-mail carries an unsubscribe link that stops all further mail from any workspace. "Report this
          page" at the bottom tells the workspace's administrators something is wrong. To have your data erased
          sooner, contact the workspace using the address in the e-mail you received.
        </p>
      </div>
    </LoginShell>
  );
}
