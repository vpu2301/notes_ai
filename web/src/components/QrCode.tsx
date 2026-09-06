import { useEffect, useState } from "react";
import QRCode from "qrcode";

/**
 * A QR code, rendered in the page.
 *
 * `qrcode` (MIT) is bundled at build time and encodes locally — the value
 * never leaves the browser, which for a TOTP provisioning URI is the whole
 * point. A hosted image service would mean mailing the shared secret to a
 * third party, and the CDN restriction in `web/README.md` rules that out
 * anyway.
 *
 * SVG rather than canvas so it stays sharp on a phone camera at any zoom
 * and inherits the page's colours.
 */
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
      // The SVG is produced by the bundled encoder from a value this app
      // built; there is no user or server HTML in it.
      dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
    />
  );
}
