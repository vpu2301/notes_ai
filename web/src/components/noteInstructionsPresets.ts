// The four "Start from an example" texts (concept §9 + Sales discovery). Byte-identical,
// plus one trailing newline, to services/note-service/tests/fixtures/instructions/<id>.txt —
// web/tests/noteInstructions.test.tsx diffs them. Choosing one fills the text and checks it;
// nothing is saved until the admin presses Save.

export interface InstructionsPreset {
  id: string;
  label: string;
  text: string;
}

export const PRESETS: readonly InstructionsPreset[] = [
  {
    id: "executive_brief",
    label: "Executive brief",
    text: "# Reader\nThe CEO. Thirty seconds.\n# Length\nShort. Four summary sentences at most.\n# Sections\nNo topic sections, no open questions. Keep decisions and tasks.\n# Emphasis\nMoney, dates, decisions, risks.\n# Wording\nPlain words. No adjectives. Avoid: synergy, align, circle back.",
  },
  {
    id: "client_ready_de",
    label: "Client-ready (German)",
    text: "# Leser\nProjektleitung beim Mandanten; liest die Notiz vollständig.\n# Umfang\nStandard.\n# Formulierung\nFormelles Geschäftsdeutsch. Verwende „Mandant“ statt „Kunde“, „Projektleitung“ statt „PM“, „Lieferobjekt“ statt „Deliverable“.\n# Schwerpunkt\nVereinbarte Liefertermine, offene Entscheidungen des Mandanten, Risiken.",
  },
  {
    id: "engineering_standup",
    label: "Engineering stand-up",
    text: "# Reader\nThe team; they skim.\n# Length\nShort. Two to four bullets per section.\n# Sections\nNo open questions (we track them in Jira). No figure tables.\n# Emphasis\nBlockers, who is waiting on whom, anything that changed the plan.\n# Wording\nUse \"PR\" not \"pull request\"; \"prod\" not \"production\". Short headings.",
  },
  {
    id: "sales_discovery",
    label: "Sales discovery",
    text: "# Reader\nThe account executive and their manager, before the next call.\n# Length\nStandard.\n# Sections\nNo figure tables. Keep open questions.\n# Emphasis\nThe customer's problem in their own words, budget, timeline, who decides, competitors mentioned.\n# Wording\nPlain words. Use \"customer\" not \"client\". Avoid: synergy, leverage.",
  },
];
