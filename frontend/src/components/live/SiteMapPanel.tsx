import { layoutMap, MAP_NODE, type SiteMap } from "../../lib/live/siteMap";

const MAX_LABEL = 26;
const HTTP_ERROR = 400;

const isError = (status: number | null) => (status ?? 0) >= HTTP_ERROR;

/** The screens found, drawn by click depth (an SVG with React text only: paths come from the application under test),
 *  and the same screens as a table, so a screen reader or a keyboard reaches every one (react review). */
export function SiteMapPanel({ map }: { map: SiteMap }) {
  const layout = layoutMap(map);
  if (!layout.nodes.length) return <p className="muted">No screen found yet.</p>;
  const at = new Map(layout.nodes.map((n) => [n.path, n]));
  const errors = layout.nodes.filter((n) => isError(n.status)).length;
  return (
    <>
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a wide map must scroll from the keyboard */}
      <div className="scroll-x" role="region" aria-label="Site map, scrolls sideways" tabIndex={0}>
        <svg className="sitemap" viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} height={layout.height} role="img"
             aria-label={`Site map: ${layout.nodes.length} screens found, ${errors} with an HTTP error`}>
          {layout.edges.map((e) => {
            const a = at.get(e.from);
            const b = at.get(e.to);
            if (!a || !b) return null;
            const x1 = a.x + MAP_NODE.width, y1 = a.y + MAP_NODE.height / 2, x2 = b.x, y2 = b.y + MAP_NODE.height / 2, mx = (x1 + x2) / 2;
            return <path key={`${e.from}>${e.to}`} className="edge" d={`M${x1} ${y1} C${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} />;
          })}
          {layout.nodes.map((n) => (
            <g key={n.path} className={`node${isError(n.status) ? " bad" : ""}${n.current ? " cur" : ""}`}>
              <rect x={n.x} y={n.y} width={MAP_NODE.width} height={MAP_NODE.height} rx={8} />
              <text x={n.x + 10} y={n.y + 16} className="node-path">{n.path.length > MAX_LABEL ? `${n.path.slice(0, MAX_LABEL - 1)}…` : n.path}</text>
              <text x={n.x + 10} y={n.y + 31} className="node-sub">{isError(n.status) ? `HTTP ${n.status}` : n.roles.join(", ")}</text>
            </g>
          ))}
        </svg>
      </div>
      <details className="screens">
        <summary>The screens as a list ({layout.nodes.length})</summary>
        {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a wide table must scroll from the keyboard */}
        <div className="scroll-x" role="region" aria-label="Screens, scrolls sideways" tabIndex={0}>
          <table aria-label="Screens found">
            <thead><tr><th scope="col">Screen</th><th scope="col">Reached by</th><th scope="col">Answer</th></tr></thead>
            <tbody>
              {layout.nodes.map((n) => (
                <tr key={n.path} className={isError(n.status) ? "bad" : undefined}>
                  <td className="mono">{n.path}{n.current ? " (now)" : ""}</td>
                  <td>{n.roles.join(", ")}</td>
                  <td>{isError(n.status) ? `HTTP ${n.status}` : "ok"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
