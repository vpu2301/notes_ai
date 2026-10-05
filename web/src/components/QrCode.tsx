import { useEffect, useState } from "react";
import QRCode from "qrcode";

/** QR code encoded locally by the bundled `qrcode` — the TOTP secret never leaves the browser.
 *  SVG so it stays sharp at any zoom. */
export function QrCode({ value, size = 180, label }: { value: string; size?: number; label: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSvg(null);
    setFailed(false);
    void QRCode.toString(value, {
      type: "svg",
      margin: 0,
      errorCorrectionLevel: "M",
      color: { dark: "#1a1816", light: "#ffffff" },
    })
      .then((out) => !cancelled && setSvg(out))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [value]);

  if (failed) {
    // Not fatal: the manual key next to this is a complete alternative.
    return (
      <div className="qr-frame" style={{ width: size, height: size }}>
        <span className="qr-fallback">Use the key below</span>
      </div>
    );
  }

  return (
    <div
      className="qr-frame"
      style={{ width: size, height: size }}
      role="img"
      aria-label={label}
      // SVG from the bundled encoder over an app-built value: no user or server HTML in it.
      dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
    />
  );
}
