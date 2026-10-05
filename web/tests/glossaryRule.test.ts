import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ORDINALS, ROLE_WORDS, ROLE_WORDS_ALL, isVocabulary } from "../src/lib/glossaryRule";

// The repo-root fixture is shared with the server and every client.
const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(resolve(here, "../../tests/fixtures/glossary/role_words.json"), "utf8"),
) as { role_words: Record<string, string[]>; ordinals: string[] };

describe("the glossary rule's tables are the shared fixture (Sprint I2)", () => {
  it("has the same role words per language", () => {
    expect(ROLE_WORDS).toEqual(fixture.role_words);
  });

  it("unions every language", () => {
    expect([...ROLE_WORDS_ALL].sort()).toEqual([...new Set(Object.values(fixture.role_words).flat())].sort());
  });

  it("has the same ordinals", () => {
    expect([...ORDINALS].sort()).toEqual([...new Set(fixture.ordinals)].sort());
  });
});

describe("a role label is not vocabulary", () => {
  it.each(["Moderator II", "moderatorin", "Narrator", "speaker background", "Sprecher 2", "Ведучий"])(
    "refuses %j as a person",
    (term) => {
      expect(isVocabulary(term, "person")).toBe(false);
    },
  );

  it("refuses a term with no words at all", () => {
    expect(isVocabulary("  ", "term")).toBe(false);
    expect(isVocabulary("---", "product")).toBe(false);
  });

  it("refuses a person written all in lowercase", () => {
    expect(isVocabulary("gregor gysi", "person")).toBe(false);
  });
});

describe("a name is vocabulary", () => {
  it.each<[string, "person" | "company" | "product" | "term"]>([
    ["Gregor Gysi", "person"],
    ["Springbrook Marine Group", "company"],
    ["Pardo", "product"],
    ["Williams Jet Tender", "product"],
    ["IPS 1350", "product"],
  ])("accepts %j as a %s", (term, kind) => {
    expect(isVocabulary(term, kind)).toBe(true);
  });

  it("only asks for a capital letter on a person", () => {
    expect(isVocabulary("pardo", "product")).toBe(true);
    expect(isVocabulary("kanban", "term")).toBe(true);
  });
});
