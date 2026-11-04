import { Link } from "react-router";
import { ArrowRight } from "@phosphor-icons/react";
import { needsYou } from "../../lib/gates";
import { useGateCounts } from "../../lib/useGateCounts";

/** The Project page's "What needs you": every gate item that waits for a person, each linked to the page that answers it. */
export function GateCounts({ slug }: { slug: string }) {
  const counts = useGateCounts(slug);
  const items = counts.data ? needsYou(counts.data, slug) : [];
  return (
    <section className="card flat needs" aria-labelledby="h-needs">
      <h2 id="h-needs">What needs you</h2>
      {counts.isPending && <p className="muted small" role="status">Checking…</p>}
      {counts.isError && <p className="muted small">The gates could not be checked just now.</p>}
      {counts.data && items.length === 0 && <p className="muted small">Nothing needs you right now.</p>}
      {items.length > 0 && (
        <ul className="list">
          {items.map((i) => (
            <li key={i.id}>
              {i.to ? (
                <Link className="list-row" to={i.to}>
                  <span>{i.text}</span>
                  <ArrowRight aria-hidden="true" />
                </Link>
              ) : (
                <span className="list-row static">{i.text}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
