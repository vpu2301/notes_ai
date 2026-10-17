import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** Routes the backend removed; no web source may call them again. */
const REMOVED = ["/admin/users/invite"];

const SRC = resolve(__dirname, "../src");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

describe("removed backend routes", () => {
  const files = sources(SRC);

  it("reads the sources", () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it.each(REMOVED)("nothing in web/src calls %s", (route) => {
    const hits = files.filter((f) => readFileSync(f, "utf8").includes(route));
    expect(hits).toEqual([]);
  });
});
