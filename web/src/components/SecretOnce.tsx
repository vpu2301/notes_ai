import { useState, type ReactNode } from "react";
import { CheckIcon, CopyIcon, DownloadIcon } from "./icons";

/**
 * A secret shown exactly once — recovery codes, a TOTP key, a device
 * secret.
 *
 * The rules this component exists to keep, in one place rather than
 * re-argued at three call sites: it holds the value in React state only,
 * it is unmounted the moment its screen is left, and the download it
 * offers is built from a `Blob` in the page. Nothing is written to
 * storage, nothing is put in a toast, and there is no way to ask for it
 * again — the server has already stopped being able to answer.
 */
export function SecretOnce({
  title,
  hint,
  values,
  filename,
  children,
}: {
  title: string;
  hint?: ReactNode;
  /** One line per value. Rendered monospaced. */
  values: string[];
  /** When given, a .txt download of the same lines is offered. */
  filename?: string;
  children?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const text = values.join("\n");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard denied — the codes are on screen to be written down */
    }
  };

  const download = () => {
    // Built here, revoked immediately: the file exists only long enough
    // for the browser to take it.
    const url = URL.createObjectURL(new Blob([text + "\n"], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = filename!;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="secret-once">
      <div className="secret-once-h">
        <strong>{title}</strong>
        <div className="secret-once-actions">
          <button type="button" className="btn ghost sm" onClick={() => void copy()}>
            {copied ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>
          {filename && (
            <button type="button" className="btn ghost sm" onClick={download}>
              <DownloadIcon size={13} />
              <span>Download</span>
            </button>
          )}
        </div>
      </div>
      <ol className="secret-once-list">
        {values.map((value) => (
          <li key={value}>
            <code>{value}</code>
          </li>
        ))}
      </ol>
      {hint && <p className="help">{hint}</p>}
      {children}
    </div>
  );
}
