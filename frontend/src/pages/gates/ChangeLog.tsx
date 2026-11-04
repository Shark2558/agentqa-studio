import { useParams } from "react-router";
import { useInfiniteQuery } from "@tanstack/react-query";
import { byWords, when, whyIsQuestion } from "../../lib/gates";
import { gatesApi, type Change } from "../../lib/gatesApi";
import { GateTop } from "../../components/gates/GateTop";

/** The Why column. An answer's row carries the question it answers, not a person's reason, so it says so. */
function Why({ change }: { change: Change }) {
  if (!change.why) return <>—</>;
  if (!whyIsQuestion(change)) return <>{change.why}</>;
  return <><span className="muted">The question: </span><span>{change.why}</span></>;
}

/** Every decision with who made it and why, newest first, 50 at a time (FR-ACC-3). */
export function ChangeLog() {
  const { slug = "" } = useParams();
  const log = useInfiniteQuery({
    queryKey: ["changes", slug],
    queryFn: ({ pageParam }) => gatesApi.changes(slug, pageParam),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_before ?? undefined,
  });
  const rows = log.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <GateTop slug={slug} title="Change log" sub={log.data ? `${rows.length} change${rows.length === 1 ? "" : "s"} shown, newest first` : "Loading…"} />
      {log.isError && <p className="notice bad" role="alert">The change log could not be loaded. Reload the page.</p>}
      {log.data && rows.length === 0 && <p className="muted">Nothing has changed yet.</p>}
      {rows.length > 0 && (
        <section className="card flat" aria-labelledby="h-changes">
          <h2 id="h-changes" className="sr-only">Changes</h2>
          <table className="rows changes">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">What</th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td className="lead mono">{when(c.at)}</td>
                  <td data-label="Who">{byWords(c.by)}</td>
                  <td className="wrap" data-label="What">
                    <span>{c.change}</span>
                    <span className="block muted small mono">{c.object} {c.object_id !== "-" ? c.object_id : ""}</span>
                  </td>
                  <td className="wrap" data-label="Why"><Why change={c} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {log.hasNextPage && (
        <button type="button" className="btn mt-4" disabled={log.isFetchingNextPage} onClick={() => log.fetchNextPage()}>Show older</button>
      )}
    </>
  );
}
