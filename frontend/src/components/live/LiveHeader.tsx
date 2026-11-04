import { Link } from "react-router";
import { liveGateText, type GateId } from "../../lib/gates";
import type { GateCounts } from "../../lib/gatesApi";
import type { BoardDef, BoardModel } from "../../lib/live/board";
import { displayState } from "../../lib/live/board";
import type { ConnStatus, Transport } from "../../lib/live/connect";
import type { Model } from "../../lib/live/model";
import type { EndReason } from "../../lib/live/stream";
import { STATE_WORDS } from "./AgentBoard";

const STATUS_WORDS: Readonly<Record<ConnStatus, string>> = {
  connecting: "connecting…", live: "live", retrying: "connection lost, retrying…", ended: "finished",
  "signed-out": "your sign-in ended: sign in again to keep watching", gone: "this run no longer exists",
  lost: "connection lost: reload the page to try again",
};
// Why a stream ended: only "finished" says the run is over (TypeScript review).
const END_WORDS: Readonly<Record<EndReason, string>> = {
  finished: "finished", idle: "no news for an hour", "signed-out": STATUS_WORDS["signed-out"], gone: STATUS_WORDS.gone,
};
const BAD: ReadonlySet<ConnStatus> = new Set(["signed-out", "gone", "lost"]);
const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

type HeaderProps = { model: Model; status: ConnStatus; ended: EndReason | null; transport: Transport | null };

/** When the run started, how many browsers it used, what the AI cost so far, and the connection in plain words (a
 *  polite status: it changes a few times a run, never per event). */
export function RunHeader({ model, status, ended, transport }: HeaderProps) {
  const b = model.board;
  const parts = [
    b.t0 !== null ? `started ${TIME.format(new Date(b.t0 * 1000))}` : null,
    model.lanes.order.length ? `${model.lanes.order.length} browser${model.lanes.order.length === 1 ? "" : "s"}` : null,
    `AI so far: ${b.ai.tokensIn.toLocaleString()} in / ${b.ai.tokensOut.toLocaleString()} out tokens · $${b.ai.cost.toFixed(4)}`,
  ];
  const words = status === "ended" && ended ? END_WORDS[ended] : STATUS_WORDS[status];
  return (
    <p className="sub run-meta" data-transport={transport ?? undefined}>
      {parts.filter(Boolean).join(" · ")} · <span role="status" className={BAD.has(status) ? "bad-text" : ""}>{words}</span>
    </p>
  );
}

const GATE_PAGES: Readonly<Record<string, GateId>> = { questions: "questions", plan: "plan", defects: "defects" };

/** A gate between stages: a link to its page (M1.4), with the recording's count and, for the newest run, what is open. */
function Gate({ gate, b, slug, now }: { gate: BoardDef["gates"][number]; b: BoardModel; slug: string; now: GateCounts | null }) {
  const page = Object.hasOwn(GATE_PAGES, gate.id) ? GATE_PAGES[gate.id] : null;
  const how = page ? liveGateText(page, b.gates, now) : "";
  const waiting = gate.id === "plan" && how === "waiting for you";
  return (
    <li className={`gate${waiting ? " waiting" : ""}`}>
      {page ? (
        <Link className="gate-link" to={`/projects/${encodeURIComponent(slug)}/${page}`}>
          <span className="what">{gate.label}</span>
          <span className="how">{how}</span>
        </Link>
      ) : (
        <span className="what">{gate.label}</span>
      )}
    </li>
  );
}

type PipelineProps = { model: Model; def: BoardDef; runOver: boolean; slug: string; now: GateCounts | null; onJump: (agent: string) => void };

/** "12 of 12 stages finished · 1 failed": a failed or skipped stage is finished, never "done". */
function progressText(states: readonly string[]): { finished: number; text: string } {
  const count = (s: string) => states.filter((x) => x === s).length;
  const finished = count("done") + count("failed") + count("skipped");
  const extra = [count("failed") ? `${count("failed")} failed` : "", count("skipped") ? `${count("skipped")} skipped` : ""].filter(Boolean);
  return { finished, text: [`${finished} of ${states.length} stages finished`, ...extra].join(" · ") };
}

/** The pipeline as a row of stages with the three human gates between them; pressing a stage jumps the replay to it,
 *  pressing a gate opens its page. `now` holds the project's gate counts when the run shown is the newest. */
export function PipelineCard({ model, def, runOver, slug, now, onJump }: PipelineProps) {
  const b = model.board;
  const stages = def.stages.map((s) => ({ ...s, card: b.cards.get(s.agent) }));
  const progress = progressText(stages.map((s) => (s.card ? displayState(s.card, b, runOver) : "queued")));
  const items = stages.flatMap((s) => {
    const before = def.gates.filter((g) => g.before === s.stage);
    const after = def.gates.filter((g) => g.after === s.stage);
    return [...before.map((g) => ({ gate: g })), { stage: s }, ...after.map((g) => ({ gate: g }))];
  });
  const done = progress.finished;
  return (
    <section className="card sunk pipeline" aria-labelledby="h-pipeline">
      <h2 id="h-pipeline" className="small-heading">
        Pipeline · {progress.text}
      </h2>
      <div className="progress" role="progressbar" aria-label="Run progress" aria-valuemin={0} aria-valuemax={stages.length} aria-valuenow={done}
           aria-valuetext={progress.text}>
        <i style={{ transform: `scaleX(${stages.length ? done / stages.length : 0})` }} />
      </div>
      <ol className="timeline-steps">
        {items.map((item) =>
          "gate" in item ? (
            <Gate key={`gate-${item.gate.id}`} gate={item.gate} b={b} slug={slug} now={now} />
          ) : (
            <li key={item.stage.stage}>
              <button type="button" className={`step ${item.stage.card ? displayState(item.stage.card, b, runOver) : "queued"}`}
                      onClick={() => onJump(item.stage.agent)}>
                <span className="what">{item.stage.stage}</span>
                <span className="how">{item.stage.card ? STATE_WORDS[displayState(item.stage.card, b, runOver)] : "Queued"}</span>
              </button>
            </li>
          ),
        )}
      </ol>
    </section>
  );
}
