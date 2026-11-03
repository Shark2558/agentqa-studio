import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

/** Requirements as the SRS stage recorded them, each with the document it came from (M1.1; dispositions and the RTM are M1.4). */
export function Requirements() {
  const { slug = "" } = useParams();
  const view = useQuery({ queryKey: ["requirements", slug], queryFn: () => api.requirements(slug) });
  const reqs = view.data?.requirements ?? [];
  const docs = view.data?.documents ?? [];

  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">
            <Link to="/">Projects</Link> / <Link to={`/projects/${encodeURIComponent(slug)}`}>{slug}</Link> / <b>Requirements</b>
          </div>
          <h1>Requirements</h1>
          <p className="sub">
            {view.data ? `${reqs.length} requirements from ${docs.length} document${docs.length === 1 ? "" : "s"}` : "Loading…"}
          </p>
        </div>
      </div>
      {view.isError && <p className="notice bad">The requirements could not be loaded.</p>}
      {view.data && reqs.length === 0 && (
        <p className="notice warn">No requirements yet. Run the pipeline (or the “srs” stage) and the Requirement Analyst fills this page.</p>
      )}
      <div className="grid g-two">
        <section className="card flat" aria-labelledby="h-reqs">
          <h2 id="h-reqs">What the application must do</h2>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Requirement</th>
                  <th>Section</th>
                  <th>Source</th>
                  <th>Kind</th>
                </tr>
              </thead>
              <tbody>
                {reqs.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td className="wrap">
                      {r.text}
                      {(r.ambiguity?.length ?? 0) > 0 && <span className="pill warn">vague</span>}
                    </td>
                    <td className="wrap muted">{r.section}</td>
                    <td className="mono small">{r.source_file}</td>
                    <td>{r.kind}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
