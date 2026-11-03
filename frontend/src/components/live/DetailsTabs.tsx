import { useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { severity, type LiveEvent } from "../../lib/live/event";
import type { Model } from "../../lib/live/model";
import type { DocRequirement, PanelsModel } from "../../lib/live/panels";
import { SiteMapPanel } from "./SiteMapPanel";

export const TABS = ["document", "map", "rules", "code", "activity"] as const;
export type Tab = (typeof TABS)[number];
const TAB_WORDS: Readonly<Record<Tab, string>> = { document: "Document", map: "Site map", rules: "Rules", code: "Code", activity: "Activity" };
const MAX_ACTIVITY = 300;
const MAX_TERMS = 20;                    // marked words per requirement (security review)
const MAX_TERM = 80;
const MAX_AGENTS = 40;

/** Requirement text with its vague words marked, as text nodes only (never HTML). The words are escaped, deduplicated
 *  and capped before they become a pattern, which is then a plain list of literals. */
function Marked({ text, terms }: { text: string; terms: readonly string[] }) {
  const words = [...new Set(terms.filter(Boolean).map((t) => t.slice(0, MAX_TERM)))].slice(0, MAX_TERMS);
  if (!words.length) return <>{text}</>;
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")).join("|")})`, "gi");
  return <>{text.split(pattern).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part))}</>;
}

function RequirementBlock({ r }: { r: DocRequirement }) {
  return (
    <div className="blk req">
      <span className="rid mono">{r.req}</span> <Marked text={r.text} terms={[...r.vague, ...r.flags]} />
      <div className="chips">
        {r.rules.map((rule, i) => <span key={`r${i}`} className="chip">{rule}</span>)}
        {r.vague.map((term, i) => <span key={`v${i}`} className="chip warn">unclear: {term}</span>)}
        {r.unclear && <span className="chip warn">no testable rule recognised</span>}
        {r.rewrites.map((w, i) => <span key={`w${i}`} className="chip ok">rewritten: {w}</span>)}
      </div>
    </div>
  );
}

function DocumentPanel({ panels }: { panels: PanelsModel }) {
  const { blocks, requirements } = panels.doc;
  if (!blocks.length) return <p className="muted">The Requirement Analyst has not read the document yet.</p>;
  return (
    <div className="doc">
      {blocks.map((b, i) => {
        const r = b.req ? requirements.get(b.req) : undefined;
        if (b.kind === "requirement" && r) return <RequirementBlock key={i} r={r} />;
        if (b.kind === "heading") return <h3 key={i} className="doc-heading">{b.text}</h3>;
        if (b.kind === "table") {
          return (
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a wide table must scroll from the keyboard
            <div key={i} className="scroll-x" role="region" aria-label="Table, scrolls sideways" tabIndex={0}>
              <table><tbody>{(b.rows ?? []).map((row, j) => <tr key={j}>{row.map((c, k) => <td key={k}>{c}</td>)}</tr>)}</tbody></table>
            </div>
          );
        }
        return <p key={i} className={b.kind === "file" ? "file small muted" : "blk"}>{b.text}</p>;
      })}
    </div>
  );
}

function RulesPanel({ panels }: { panels: PanelsModel }) {
  const { counts, rows, questions } = panels.rules;
  return (
    <div>
      <div className="legend">{[...counts].map(([status, n]) => <span key={status} className="pill neutral">{n} {status}</span>)}</div>
      {questions.length > 0 && <ul className="questions">{questions.map((q, i) => <li key={i}><b>Question for you:</b> {q}</li>)}</ul>}
      {rows.length === 0 && <p className="muted">The Reconciler has not compared rules yet.</p>}
      <ul className="rules">
        {rows.map((r, i) => <li key={i}><span className="rid mono">{r.req}</span> {r.ruleKind}{r.field ? ` · ${r.field}` : ""} — <b>{r.status}</b>{r.where ? ` (matched ${r.where})` : ""}</li>)}
      </ul>
    </div>
  );
}

function CodePanel({ panels }: { panels: PanelsModel }) {
  const files = [...panels.code.values()];
  const [chosen, setChosen] = useState<string | null>(null);
  const file = files.find((f) => f.file === chosen) ?? files[files.length - 1];
  if (!file) return <p className="muted">No test code generated yet.</p>;
  return (
    <div>
      <div className="files">{files.map((f) => <button key={f.file} type="button" className="btn sm" aria-pressed={f === file} onClick={() => setChosen(f.file)}>{f.file} ({f.tests})</button>)}</div>
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrolling code box must be reachable by keyboard */}
      <pre className="code" role="region" tabIndex={0} aria-label={`Generated code: ${file.file}`}>{file.preview}</pre>
    </div>
  );
}

type ActivityProps = { events: readonly LiveEvent[]; pos: number; labels: (agent: string) => string };

/** The newest 300 events up to the replay position, newest first; read only while this tab is open. */
function ActivityPanel({ events, pos, labels }: ActivityProps) {
  const [agent, setAgent] = useState("");
  const [problems, setProblems] = useState(false);
  const shown = useMemo(() => events.slice(0, pos), [events, pos]);
  const agents = useMemo(() => [...new Set(shown.map((e) => e.agent))].slice(0, MAX_AGENTS), [shown]);
  const rows = useMemo(
    () => shown.filter((e) => (!agent || e.agent === agent) && (!problems || severity(e) === "bad" || severity(e) === "warn")).slice(-MAX_ACTIVITY).reverse(),
    [shown, agent, problems],
  );
  return (
    <div>
      <div className="row">
        <label className="small">Agent <select value={agent} onChange={(e) => setAgent(e.target.value)}><option value="">all agents</option>{agents.map((a) => <option key={a} value={a}>{labels(a)}</option>)}</select></label>
        <label className="check small"><input type="checkbox" checked={problems} onChange={(e) => setProblems(e.target.checked)} /> problems only</label>
      </div>
      <ul className="activity">{rows.map((e) => <li key={`${e.w}-${e.seq}`} className={severity(e) ?? ""}><span className="who">{labels(e.agent)}</span> {e.title}</li>)}</ul>
    </div>
  );
}

type Props = { model: Model; events: readonly LiveEvent[]; pos: number; tab: Tab; onTab: (t: Tab) => void; labels: (agent: string) => string };

/** The details under the board (WAI-ARIA tabs: arrow keys, Home and End move between them). */
export function DetailsTabs({ model, events, pos, tab, onTab, labels }: Props) {
  const id = useId();
  const refs = useRef<Partial<Record<Tab, HTMLButtonElement | null>>>({});
  const move = (e: KeyboardEvent, i: number) => {
    const next = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i + TABS.length - 1) % TABS.length
               : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    onTab(TABS[next]);
    refs.current[TABS[next]]?.focus();
  };
  const panels: Readonly<Record<Tab, () => ReactNode>> = {
    document: () => <DocumentPanel panels={model.panels} />, map: () => <SiteMapPanel map={model.map} />,
    rules: () => <RulesPanel panels={model.panels} />, code: () => <CodePanel panels={model.panels} />,
    activity: () => <ActivityPanel events={events} pos={pos} labels={labels} />,
  };
  return (
    <section className="card details" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="sr-only">Details</h2>
      <div className="tabs" role="tablist" aria-label="Detail views">
        {TABS.map((t, i) => (
          <button key={t} ref={(el) => { refs.current[t] = el; }} type="button" role="tab" id={`${id}-${t}`} aria-selected={tab === t}
                  aria-controls={tab === t ? `${id}-panel` : undefined} tabIndex={tab === t ? 0 : -1} onClick={() => onTab(t)} onKeyDown={(e) => move(e, i)}>
            {TAB_WORDS[t]}
          </button>
        ))}
      </div>
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a tab panel takes focus when it has no control of its own */}
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}`} className="tab-panel" tabIndex={0}>{panels[tab]()}</div>
    </section>
  );
}
