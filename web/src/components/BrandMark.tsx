/* BrandMark — the product mark, one shape across web, macOS and iOS.
 *
 * DSBrandMark (macos|ios/…/Views/Theme.swift) draws a `.continuous` rounded
 * rectangle with the product initial reversed out of it. CSS `border-radius`
 * draws a circular arc instead — the boxier corner — so the mark is an inline
 * SVG here and the outline is a real superellipse, |x/a|^4.6 + |y/a|^4.6 = 1,
 * walked at 64 points on a 32-unit grid. Every browser then gets the same
 * squircle the app icons have, and it is the same curve index.html cuts the
 * favicon from.
 */

const SQUIRCLE =
  "M31 16 30.97 21.46 30.87 23.37 30.72 24.76 30.49 25.88 30.2 26.82 29.84 27.62 " +
  "29.41 28.31 28.9 28.9 28.31 29.41 27.62 29.84 26.82 30.2 25.88 30.49 24.76 30.72 " +
  "23.37 30.87 21.46 30.97 16 31 10.54 30.97 8.63 30.87 7.24 30.72 6.12 30.49 " +
  "5.18 30.2 4.38 29.84 3.69 29.41 3.1 28.9 2.59 28.31 2.16 27.62 1.8 26.82 " +
  "1.51 25.88 1.28 24.76 1.13 23.37 1.03 21.46 1 16 1.03 10.54 1.13 8.63 1.28 7.24 " +
  "1.51 6.12 1.8 5.18 2.16 4.38 2.59 3.69 3.1 3.1 3.69 2.59 4.38 2.16 5.18 1.8 " +
  "6.12 1.51 7.24 1.28 8.63 1.13 10.54 1.03 16 1 21.46 1.03 23.37 1.13 24.76 1.28 " +
  "25.88 1.51 26.82 1.8 27.62 2.16 28.31 2.59 28.9 3.1 29.41 3.69 29.84 4.38 " +
  "30.2 5.18 30.49 6.12 30.72 7.24 30.87 8.63 30.97 10.54z";

/** The "N" of the wordmark, drawn to the same grid. */
const INITIAL = "M10 23V9h3l7 9.5V9h3v14h-3l-7-9.5V23z";

interface BrandMarkProps {
  size?: number;
  /** Ink tile in the sidebar; moss where the mark stands alone on paper. */
  tone?: "ink" | "accent";
}

export function BrandMark({ size = 26, tone = "ink" }: BrandMarkProps) {
  const fill = tone === "accent" ? "var(--accent)" : "var(--ink)";
  const on = tone === "accent" ? "var(--accent-ink)" : "var(--ink-text)";
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path d={SQUIRCLE} fill={fill} />
      <path d={INITIAL} fill={on} />
    </svg>
  );
}
