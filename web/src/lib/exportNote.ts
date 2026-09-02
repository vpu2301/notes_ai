/** Client-side exports: the note as a file the user keeps. */

export interface ExportSection {
  name: string;
  text: string;
}

export function noteToMarkdown(opts: {
  title: string;
  code: string;
  updatedAt?: string;
  sections: ExportSection[];
}): string {
  const lines: string[] = [`# ${opts.title.trim() || "Untitled note"}`, ""];
  const meta = [opts.code, opts.updatedAt ? new Date(opts.updatedAt).toLocaleString() : ""]
    .filter(Boolean)
    .join(" · ");
  if (meta) lines.push(`_${meta}_`, "");
  for (const s of opts.sections) {
    if (!s.text.trim()) continue;
    lines.push(`## ${s.name}`, "", s.text.trim(), "");
  }
  return lines.join("\n");
}

/** Hand a blob to the browser as a download. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function safeFilename(title: string, fallback: string): string {
  const base = title
    .trim()
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, " ")
    .slice(0, 80)
    .trim();
  return base || fallback;
}
