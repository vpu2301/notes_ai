// The sidebar's "Spaces" section — the same personal folders the Mac app
// shows: click one to narrow the notes list, ⋯ to rename or delete it.

import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import type { Space } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FolderIcon, PenIcon, PlusIcon, TrashIcon } from "../components/icons";
import { Menu } from "../components/Menu";
import { useSpaces } from "../spaces/SpacesContext";

function SpaceRow({ space, collapsed }: { space: Space; collapsed: boolean }) {
  const { rename, remove } = useSpaces();
  const { spaceId } = useParams();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (draft !== null) inputRef.current?.select();
  }, [draft]);

  const commit = () => {
    const name = draft ?? "";
    setDraft(null);
    if (name.trim() && name.trim() !== space.name) void rename(space.id, name);
  };

  if (draft !== null && !collapsed) {
    return (
      <div className="sb-space-edit">
        <FolderIcon size={14} />
        <input
          ref={inputRef}
          className="sb-space-input"
          value={draft}
          aria-label="Space name"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            else if (e.key === "Escape") setDraft(null);
          }}
        />
      </div>
    );
  }

  return (
    <>
      <div className="sb-space">
        <NavLink
          to={`/spaces/${space.id}`}
          className={({ isActive }) => `sb-link ${isActive ? "on" : ""}`}
          title={collapsed ? space.name : undefined}
        >
          <FolderIcon size={14} />
          <span className="sb-link-label">{space.name}</span>
          {space.note_ids.length > 0 && <span className="sb-count">{space.note_ids.length}</span>}
        </NavLink>
        {!collapsed && (
          <span className="sb-space-more">
            <Menu
              anchored
              label={`Actions for ${space.name}`}
              items={[
                { label: "Rename", icon: <PenIcon size={14} />, onClick: () => setDraft(space.name) },
                {
                  label: "Delete space",
                  icon: <TrashIcon size={14} />,
                  danger: true,
                  onClick: () => setConfirmDelete(true),
                },
              ]}
            />
          </span>
        )}
      </div>
      {confirmDelete && (
        <ConfirmDialog
          title={`Delete “${space.name}”?`}
          subtitle="The notes filed here stay — they go back to All notes."
          confirmLabel="Delete space"
          confirmDanger
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => {
            setConfirmDelete(false);
            if (spaceId === space.id) navigate("/", { replace: true });
            void remove(space.id);
          }}
        />
      )}
    </>
  );
}

export function SpacesNav({ collapsed }: { collapsed: boolean }) {
  const { spaces, loading, error, refresh, create } = useSpaces();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  const commit = () => {
    const value = name;
    setAdding(false);
    setName("");
    if (value.trim()) void create(value);
  };

  return (
    <div className="sb-spaces">
      {!collapsed && (
        <div className="sb-section-h">
          <span>Spaces</span>
          <button
            className="sb-section-add"
            title="New space"
            aria-label="New space"
            onClick={() => {
              setName("");
              setAdding(true);
            }}
          >
            <PlusIcon size={13} />
          </button>
        </div>
      )}

      {spaces.map((space) => (
        <SpaceRow key={space.id} space={space} collapsed={collapsed} />
      ))}

      {adding && !collapsed && (
        <div className="sb-space-edit">
          <FolderIcon size={14} />
          <input
            ref={inputRef}
            className="sb-space-input"
            value={name}
            placeholder="Space name"
            aria-label="New space name"
            onChange={(e) => setName(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              else if (e.key === "Escape") {
                setAdding(false);
                setName("");
              }
            }}
          />
        </div>
      )}

      {!collapsed && error && (
        <p className="sb-hint">
          Spaces are unavailable.{" "}
          <button className="link-btn" onClick={() => void refresh()}>
            Try again
          </button>
        </p>
      )}

      {!collapsed && !loading && !error && spaces.length === 0 && !adding && (
        <p className="sb-hint">Spaces keep notes together — a client, a project, a team.</p>
      )}
    </div>
  );
}
