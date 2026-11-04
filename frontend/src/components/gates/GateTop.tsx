import type { ReactNode } from "react";
import { Link } from "react-router";

type Props = { slug: string; title: string; sub: string; children?: ReactNode };

/** A gate page's header: where you are, the page's name, one line of counts, and its actions on the right. */
export function GateTop({ slug, title, sub, children }: Props) {
  return (
    <div className="topbar">
      <div>
        <div className="crumbs">
          <Link to="/">Projects</Link> / <Link to={`/projects/${encodeURIComponent(slug)}`}>{slug}</Link> / <b>{title}</b>
        </div>
        <h1>{title}</h1>
        <p className="sub">{sub}</p>
      </div>
      {children && (
        <>
          <div className="spacer" />
          {children}
        </>
      )}
    </div>
  );
}
