import { useParams } from "react-router";
import { useInfiniteQuery } from "@tanstack/react-query";
import { DownloadSimple } from "@phosphor-icons/react";
import { useMe } from "../App";
import { canWrite } from "../lib/can";
import { gateFiles, gatesApi, type GatedRequirement } from "../lib/gatesApi";
import { DispositionControl } from "../components/gates/DispositionControl";
import { GateTop } from "../components/gates/GateTop";

// How each disposition reads, and its colour: covered and gap are AgentQA's own; the other four are a person's.
const DISPOSITION: Readonly<Record<string, [tone: string, words: string]>> = {
  covered: ["ok", "covered"], gap: ["bad", "not covered"], out_of_scope: ["neutral", "out of scope"],
  not_testable: ["neutral", "not testable"], manual: ["info", "tested by hand"], clarify: ["info", "to clarify"],
};

function DispositionCell({ r, slug, mayWrite }: { r: GatedRequirement; slug: string; mayWrite: boolean }) {
  const [tone, words] = r.disposition && Object.hasOwn(DISPOSITION, r.disposition) ? DISPOSITION[r.disposition] : ["neutral", r.disposition ?? "not yet"];
  return (
    <td className="wrap" data-label="Disposition">
      <span className={`pill ${tone}`}>{words}</span>
      {r.disposition_note && <span className="block small muted">{r.disposition_note}</span>}
      {mayWrite && <DispositionControl slug={slug} rid={r.id} />}
    </td>
  );
}

/** Requirements as the Requirement Analyst recorded them, 200 at a time, each with its disposition (FR-ONB-4): a
 *  person may mark one out of scope, not testable, tested by hand or to clarify, always with a reason. */
export function Requirements() {
  const { slug = "" } = useParams();
  const mayWrite = canWrite(useMe().data?.role);
  const view = useInfiniteQuery({
    queryKey: ["requirements", slug],
    queryFn: ({ pageParam }) => gatesApi.requirements(slug, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.requirements.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
  const pages = view.data?.pages ?? [];
  const reqs = pages.flatMap((p) => p.requirements);
  const docs = pages[0]?.documents ?? [];
  const total = pages.at(-1)?.total ?? 0;
  const shown = reqs.length === total ? `${total} requirements` : `${reqs.length} of ${total} requirements`;
  const sub = view.data ? `${shown} from ${docs.length} document${docs.length === 1 ? "" : "s"}` : "Loading…";

  return (
    <>
      <GateTop slug={slug} title="Requirements" sub={sub}>
        <a className="btn" href={gateFiles.rtm(slug)} download>
          <DownloadSimple aria-hidden="true" />
          Download the traceability matrix (Excel)
        </a>
      </GateTop>
      {view.isError && <p className="notice bad" role="alert">The requirements could not be loaded.</p>}
      {view.data && reqs.length === 0 && (
        <p className="notice warn">No requirements yet. Run the pipeline (or the “srs” stage) and the Requirement Analyst fills this page.</p>
      )}
      <div className="grid">
        <section className="card flat" aria-labelledby="h-reqs">
          <h2 id="h-reqs">What the application must do</h2>
          <table className="rows reqs">
            <thead>
              <tr>
                <th scope="col">ID</th>
                <th scope="col">Requirement</th>
                <th scope="col">Disposition</th>
              </tr>
            </thead>
            <tbody>
              {reqs.map((r) => (
                <tr key={r.id}>
                  <td className="lead mono">{r.id}</td>
                  <td className="wrap" data-label="Requirement">
                    {r.text}
                    {(r.ambiguity?.length ?? 0) > 0 && <span className="pill warn">vague</span>}
                    <span className="block small muted">{[r.section, r.source_file].filter(Boolean).join(" · ")}</span>
                  </td>
                  <DispositionCell r={r} slug={slug} mayWrite={mayWrite} />
                </tr>
              ))}
            </tbody>
          </table>
          {view.hasNextPage && (
            <button type="button" className="btn" disabled={view.isFetchingNextPage} onClick={() => view.fetchNextPage()}>Show more</button>
          )}
        </section>
        <section className="card flat" aria-labelledby="h-sources">
          <h2 id="h-sources">Sources</h2>
          <ul className="list">
            {docs.map((d) => (
              <li key={d.name} className="list-row static">
                <span>
                  <b>{d.name}</b>
                  <span className="muted small">
                    {d.segments} pieces of text{d.detail ? ` · ${d.detail}` : ""}
                  </span>
                </span>
                <span className={`pill ${d.status === "read" ? "ok" : "bad"}`}>{d.status === "read" ? "read" : "not read"}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
