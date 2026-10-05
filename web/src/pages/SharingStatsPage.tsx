import { useEffect, useState } from "react";
import { sharingStats } from "../api/admin";
import type { SharingStats } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ShareIcon } from "../components/icons";
import { Skeleton } from "../components/Skeleton";
import { messageFor } from "../lib/errorCopy";
import { useDocumentTitle } from "../lib/useDocumentTitle";

/**
 * `/admin/sharing` — the workspace's recipient loop in four tiles (Sprint 22).
 * Counts only; the API refuses anyone without `stats.read`, so this
 * page is also only linked for a workspace admin.
 */
export function SharingStatsPage() {
  useDocumentTitle("Sharing");
  const [days, setDays] = useState<30 | 90>(30);
  const [stats, setStats] = useState<SharingStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setStats(null);
    setError(null);
    sharingStats(days)
      .then((s) => live && setStats(s))
      .catch((err) => live && setError(messageFor(err)));
    return () => {
      live = false;
    };
  }, [days]);

  const pct = (n: number, d: number) => (d ? `${Math.round((100 * n) / d)}%` : "—");
  const nothingYet = stats !== null && stats.links_created === 0 && stats.links_sent === 0;

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
      {!stats && !error && (
        <div className="stat-tiles" aria-busy="true" aria-label="Loading sharing figures">
          <Skeleton height={86} />
          <Skeleton height={86} />
          <Skeleton height={86} />
          <Skeleton height={86} />
        </div>
      )}
      {nothingYet && (
        <EmptyState
          icon={<ShareIcon size={20} />}
          title={`Nothing shared in the last ${days} days`}
          message="When someone in the workspace sends a note to a client, the figures appear here."
        />
      )}
      {stats && !nothingYet && (
        <>
          <div className="stat-tiles">
            <Tile label="Links sent" value={String(stats.links_sent)} sub={`${stats.links_created} created`} />
            <Tile label="Opened" value={pct(stats.links_opened, stats.links_sent)} sub={`${stats.links_opened} of ${stats.links_sent} sent`} />
            <Tile label="Responded" value={pct(stats.links_responded, stats.links_opened)} sub={`${stats.links_responded} of ${stats.links_opened} opened`} />
            <Tile label="Sign-up clicks" value={String(stats.cta_clicks)} sub={`${Math.round(stats.dispute_rate * 100)}% disputed · ${stats.opted_out} opted out`} />
          </div>
          {stats.top_senders.length > 0 && (
            <section className="doc-section">
              <h2 className="section-name">Top senders</h2>
              <ul className="share-people" aria-label="Top senders">
                {stats.top_senders.map((s, i) => (
                  // The row carries no id; a name can repeat, so the position disambiguates.
                  <li key={`${i}-${s.display_name}`}>
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
