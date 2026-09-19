import { useEffect, useState } from "react";
import { sharingStats } from "../api/admin";
import { errorMessage } from "../api/http";
import type { SharingStats } from "../api/types";

/**
 * `/admin/sharing` — the workspace's recipient loop in four tiles (Sprint 22).
 * Counts only; the API refuses anyone without `stats.read`, so this
 * page is also only linked for a workspace admin.
 */
export function SharingStatsPage() {
  const [days, setDays] = useState<30 | 90>(30);
  const [stats, setStats] = useState<SharingStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setStats(null);
    sharingStats(days)
      .then((s) => live && setStats(s))
      .catch((err) => live && setError(errorMessage(err)));
    return () => {
      live = false;
    };
  }, [days]);

  const pct = (n: number, d: number) => (d ? `${Math.round((100 * n) / d)}%` : "—");

  return (
    <div className="doc">
      <div className="page-h">
        <h1>Sharing</h1>
        <div className="seg" role="group" aria-label="Range">
          {([30, 90] as const).map((d) => (
            <button key={d} type="button" className="seg-opt" aria-pressed={days === d} onClick={() => setDays(d)}>
              {d} days
            </button>
          ))}
        </div>
      </div>
      {error && (
        <div className="banner banner-danger" role="alert">
          {error}
        </div>
      )}
      {stats && (
        <>
          <div className="stat-tiles">
            <Tile label="Links sent" value={String(stats.links_sent)} sub={`${stats.links_created} created`} />
            <Tile label="Opened" value={pct(stats.links_opened, stats.links_sent)} sub={`${stats.links_opened} of ${stats.links_sent} sent`} />
            <Tile label="Responded" value={pct(stats.links_responded, stats.links_opened)} sub={`${stats.links_responded} of ${stats.links_opened} opened`} />
            <Tile label="CTA clicks" value={String(stats.cta_clicks)} sub={`${Math.round(stats.dispute_rate * 100)}% disputed · ${stats.opted_out} opted out`} />
          </div>
          {stats.top_senders.length > 0 && (
            <section className="doc-section">
              <h2 className="section-name">Top senders</h2>
              <ul className="share-people" aria-label="Top senders">
                {stats.top_senders.map((s) => (
                  <li key={s.display_name}>
                    <span className="row-name">{s.display_name}</span>
                    <span className="help">{s.links} links</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="stat-tile">
      <span className="label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="help">{sub}</span>
    </div>
  );
}
