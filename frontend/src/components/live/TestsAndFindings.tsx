import type { ReactNode } from "react";
import { CheckCircle, CircleDashed, Eye, Prohibit, Question, Spinner, Warning, XCircle } from "@phosphor-icons/react";
import { shownFindings, tileCounts, tileStatus, type PanelsModel, type ShownTileStatus, type Tile } from "../../lib/live/panels";

const TILE: Readonly<Record<ShownTileStatus, { word: string; css: string; icon: ReactNode }>> = {
  passed: { word: "passed", css: "ok", icon: <CheckCircle aria-hidden="true" /> },
  defect: { word: "failed", css: "bad", icon: <XCircle aria-hidden="true" /> },
  visual: { word: "visual change", css: "visual", icon: <Eye aria-hidden="true" /> },
  blocked: { word: "blocked", css: "warn", icon: <Prohibit aria-hidden="true" /> },
  "not-run": { word: "not run", css: "", icon: <CircleDashed aria-hidden="true" /> },
  "test-issue": { word: "test issue", css: "warn", icon: <Warning aria-hidden="true" /> },
  running: { word: "running", css: "run", icon: <Spinner aria-hidden="true" /> },
  "no-result": { word: "no result", css: "warn", icon: <Question aria-hidden="true" /> },
};
const ORDER: readonly ShownTileStatus[] = ["passed", "defect", "visual", "blocked", "test-issue", "running", "no-result", "not-run"];

/** The tests that did not pass, with what went wrong, so the reason is not only in a mouse tooltip (react review). */
function NotPassed({ tiles, runOver }: { tiles: readonly Tile[]; runOver: boolean }) {
  const open = tiles.filter((t) => !["passed", "running"].includes(tileStatus(t, runOver)));
  if (!open.length) return null;
  return (
    <details className="not-passed">
      <summary>Tests that did not pass ({open.length})</summary>
      <ul aria-label="Tests that did not pass">
        {open.map((t) => (
          <li key={t.id}>
            <span className="rid mono">{t.id}</span> <b>{TILE[tileStatus(t, runOver)].word}</b> · {t.title}
            {t.message && <span className="muted small"> — {t.message}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** One square per test; Blocked, Not run and a test issue are never shown as a pass. */
export function TestTiles({ panels, runOver }: { panels: PanelsModel; runOver: boolean }) {
  const counts = tileCounts(panels, runOver);
  const passed = counts.passed ?? 0;
  const tiles = panels.tileOrder.flatMap((id) => panels.tiles.get(id) ?? []);
  return (
    <section className="card" aria-labelledby="h-tests">
      <h2 id="h-tests">
        Tests <span className="cost">{panels.tileOrder.length} · {passed} passed</span>
      </h2>
      {tiles.length === 0 && <p className="muted">No test planned yet.</p>}
      <ul className="tiles" aria-label="Test results, one square per test">
        {tiles.map((tile) => {
          const s = TILE[tileStatus(tile, runOver)];
          return (
            <li key={tile.id} className={`tile ${s.css}`} aria-label={`${tile.id} ${s.word}`} title={`${tile.id}: ${tile.title}${tile.message ? `\n${tile.message}` : ""}`}>
              {s.icon}
            </li>
          );
        })}
      </ul>
      <div className="legend">
        {ORDER.filter((k) => counts[k]).map((k) => (
          <span key={k} className={`pill ${TILE[k].css || "neutral"}`}>
            {TILE[k].icon}
            {counts[k]} {TILE[k].word}
          </span>
        ))}
      </div>
      <NotPassed tiles={tiles} runOver={runOver} />
    </section>
  );
}

const KIND_WORDS = { defect: "Defect", finding: "Finding", heal: "Heal", report: "Report" } as const;

/** Defects worst first (exploratory findings fold into them once triage has drafted defects), heals and the report,
 *  in a list that scrolls inside its card; the panel says how many it had to leave out. */
export function Findings({ panels }: { panels: PanelsModel }) {
  const findings = shownFindings(panels);
  return (
    <section className="card" aria-labelledby="h-findings">
      <h2 id="h-findings">Findings</h2>
      {findings.length === 0 && <p className="muted">Nothing found yet.</p>}
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrolling list must be reachable by keyboard */}
      <ul className="findings" aria-label="Findings, worst first" tabIndex={0}>
        {findings.map((f) => (
          <li key={`${f.kind}-${f.order}`}>
            <span className="sev mono">{f.severity ?? KIND_WORDS[f.kind]}</span>
            <span>
              <b>{f.title}</b>
              {f.detail && <span className="muted small"> {f.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
      {panels.hiddenFindings > 0 && (
        <p className="muted small">{panels.hiddenFindings} more not shown: this run reported more than the page keeps of each kind.</p>
      )}
    </section>
  );
}
