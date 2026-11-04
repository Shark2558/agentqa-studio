import { useState } from "react";
import { DownloadSimple } from "@phosphor-icons/react";
import { exportLinks } from "../../lib/gates";

/** The defect downloads: confirmed defects only unless "Include drafts" is ticked (decision 5). Plain links from this
 *  page, which the server accepts (a download started from another site is refused). */
export function ExportLinks({ slug }: { slug: string }) {
  const [drafts, setDrafts] = useState(false);
  return (
    <section className="card flat" aria-labelledby="h-downloads">
      <h2 id="h-downloads">Downloads</h2>
      <label className="check">
        <input type="checkbox" checked={drafts} onChange={(e) => setDrafts(e.target.checked)} />
        Include drafts
      </label>
      <p className="small muted">
        {drafts ? "The files also hold defects nobody has confirmed yet." : "The files hold the defects you confirmed. Tick “Include drafts” to add the ones still waiting."}
      </p>
      <ul className="downloads">
        {exportLinks(slug, drafts).map((l) => (
          <li key={l.id}>
            <a className="btn" href={l.href} download>
              <DownloadSimple aria-hidden="true" />
              {l.label}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
