/** Labels a note carries in its own language (the run's `language`), never the viewer's locale. */
export type NoteLang = "en" | "de" | "uk";

const ALSO_SAID: Record<NoteLang, string> = {
  en: "Also said",
  de: "Außerdem gesagt",
  uk: "Також сказано",
};

/** The "Also said" label for a note written in `language`; English when unknown. */
export function alsoSaidLabel(language: string | null | undefined): string {
  return ALSO_SAID[(language ?? "en") as NoteLang] ?? ALSO_SAID.en;
}

/** B4 — what a written line is, in the note's language. `count` is the facts a composed
 *  sentence rests on ("Aus 2 Aussagen"). */
export function provenanceLabel(
  language: string | null | undefined,
  provenance: string | null | undefined,
  count = 2,
): string | null {
  const lang = (language ?? "en") as NoteLang;
  switch (provenance) {
    case "verbatim":
      return { en: "Verbatim", de: "Wörtlich", uk: "Дослівно" }[lang] ?? "Verbatim";
    case "paraphrase":
      return { en: "Paraphrase", de: "Paraphrase", uk: "Парафраз" }[lang] ?? "Paraphrase";
    case "composed": {
      const n = Math.max(2, count);
      return (
        { en: `From ${n} statements`, de: `Aus ${n} Aussagen`, uk: `З ${n} висловлювань` }[lang] ??
        `From ${n} statements`
      );
    }
    default:
      return null;
  }
}
