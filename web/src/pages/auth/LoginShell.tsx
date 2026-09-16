import { useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { BrandMark } from "../../components/BrandMark";
import { AlertIcon } from "../../components/icons";

/** The dotted card every signed-out screen sits in. */
export function LoginShell({
  title,
  subtitle,
  children,
  onSubmit,
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  /** When given, the card is a real `<form>` so Enter submits and password
   *  managers recognise it. */
  onSubmit?: (e: FormEvent) => void;
}) {
  const brand = (
    <>
      <div className="login-brand">
        <span className="sb-brand-mark lg" aria-hidden="true">
          <BrandMark size={34} tone="accent" />
        </span>
        <div className="login-brand-name">
          Notes <span className="ai">AI</span>
        </div>
      </div>
      <div>
        <h1 className="login-title">{title}</h1>
        {subtitle && <p className="login-sub">{subtitle}</p>}
      </div>
      {children}
    </>
  );

  return (
    <div className="login-shell dotted">
      {onSubmit ? (
        <form className="login-card" onSubmit={onSubmit}>
          {brand}
        </form>
      ) : (
        <div className="login-card">{brand}</div>
      )}
    </div>
  );
}

export function Banner({ children, tone = "danger" }: { children: ReactNode; tone?: "danger" | "info" }) {
  return (
    <div className={`banner banner-${tone}`} role="alert">
      <AlertIcon size={15} />
      <span className="grow">{children}</span>
    </div>
  );
}

/**
 * Ticks a seconds counter down to zero.
 *
 * The setter is held in a ref so that passing an inline `setState` does not
 * tear down and rebuild the interval on every tick.
 */
export function useCountdown(seconds: number, set: (n: number) => void) {
  const setRef = useRef(set);
  setRef.current = set;
  useEffect(() => {
    if (seconds <= 0) return;
    const id = window.setTimeout(() => setRef.current(seconds - 1), 1000);
    return () => window.clearTimeout(id);
  }, [seconds]);
}
