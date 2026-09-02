import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../api/http";
import { createNote, getTemplate, listTemplates } from "../api/notes";
import type { NoteContent, TemplateSummary } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { LayersIcon } from "../components/icons";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toaster";

export function NewNotePage() {
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null);
  const [creatingId, setCreatingId] = useState<string | null>(null);
  const navigate = useNavigate();
  const toast = useToast();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await listTemplates();
        if (!cancelled) setTemplates(list.filter((t) => t.status !== "archived"));
      } catch (err) {
        if (!cancelled) {
          setTemplates([]);
          toast.error(errorMessage(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grouped = useMemo(() => {
    const byCategory = new Map<string, TemplateSummary[]>();
    for (const t of templates ?? []) {
      const list = byCategory.get(t.category) ?? [];
      list.push(t);
      byCategory.set(t.category, list);
    }
    for (const list of byCategory.values()) {
      list.sort((a, b) => a.name.localeCompare(b.name));
    }
    return [...byCategory.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [templates]);

  const onPick = async (summary: TemplateSummary) => {
    if (creatingId) return;
    setCreatingId(summary.id);
    try {
      // Fetch the full definition so sections seed from default_content.
      const detail = await getTemplate(summary.id);
      const sections = [...(detail.schema_jsonb.sections ?? [])]
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
        .map((s) => ({
          section_key: s.id,
          text: s.default_content ?? "",
          field_specific_metadata: {},
        }));
      const content: NoteContent = {
        template_id: detail.id,
        template_schema_version: detail.schema_version,
        title: "",
        sections,
      };
      const created = await createNote(content);
      toast.success(`Created ${created.code}`);
      navigate(`/notes/${created.id}`);
    } catch (err) {
      toast.error(errorMessage(err));
      setCreatingId(null);
    }
  };

  return (
    <>
      <div className="page-h">
        <div>
          <h1>New note</h1>
          <p className="sub">Pick a template to start from. Sections come pre-filled with their defaults.</p>
        </div>
      </div>

      {templates === null && (
        <div className="tpl-grid" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card tpl-card" aria-hidden="true">
              <div className="tpl-card-h">
                <Skeleton width={32} height={32} style={{ borderRadius: 9 }} />
                <Skeleton width="60%" height={14} />
              </div>
              <Skeleton width="40%" height={12} />
            </div>
          ))}
        </div>
      )}

      {templates !== null && templates.length === 0 && (
        <div className="panel">
          <EmptyState
            icon={<LayersIcon size={20} />}
            title="No templates available"
            message="Your workspace has no note templates yet. Ask an administrator to add some."
          />
        </div>
      )}

      {grouped.map(([category, list]) => (
        <section key={category} aria-label={category}>
          <h2 className="tpl-cat">{category.replace(/_/g, " ")}</h2>
          <div className="tpl-grid">
            {list.map((t) => (
              <button
                key={t.id}
                className="card card-hover tpl-card"
                onClick={() => void onPick(t)}
                disabled={creatingId !== null}
                aria-busy={creatingId === t.id}
              >
                <span className="tpl-card-h">
                  <span className="row-ico">
                    <LayersIcon size={15} />
                  </span>
                  <span className="tpl-name">{creatingId === t.id ? "Creating…" : t.name}</span>
                </span>
                <span className="tpl-meta">
                  <span className="lang-tag">{t.language}</span>
                  <span className="code-tag">{t.code}</span>
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
