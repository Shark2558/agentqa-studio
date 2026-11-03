import { useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../../lib/api";
import { aiApi, errorText, settingsFrom, type AiSettingsInput, type LocalRow, type Tier } from "../../lib/ai";
import { AiForm } from "../../components/ai/AiForm";
import { LocalCard } from "../../components/ai/LocalCard";
import { UsageMeter } from "../../components/ai/UsageMeter";
import { Providers } from "../../components/ai/Providers";

const same = (a: AiSettingsInput, b: AiSettingsInput) => JSON.stringify(a) === JSON.stringify(b);
const notFound = (e: unknown) => e instanceof ApiError && e.status === 404;

/** The route element: one page instance per project, so a draft never follows the owner to another project. */
export function AiSettings() {
  const { slug = "" } = useParams();
  return <AiSettingsPage key={slug} slug={slug} />;
}

/** The project's AI page: mode, consent, budget and per-agent tiers in one form; spend, local detection and the
 *  shared provider keys beside it. Everything the owner saves goes to PUT /projects/{slug}/ai. */
function AiSettingsPage({ slug }: { slug: string }) {
  const queryClient = useQueryClient();
  const project = useQuery({ queryKey: ["project", slug], queryFn: () => api.project(slug) });
  const ai = useQuery({ queryKey: ["ai", "project", slug], queryFn: () => aiApi.project(slug) });
  const usage = useQuery({ queryKey: ["ai", "usage", slug], queryFn: () => aiApi.usage(slug) });
  const catalog = useQuery({ queryKey: ["ai", "catalog"], queryFn: aiApi.catalog });
  const keys = useQuery({ queryKey: ["ai", "keys"], queryFn: aiApi.keys });
  const local = useQuery({ queryKey: ["ai", "local"], queryFn: aiApi.local });
  const policy = useQuery({ queryKey: ["ai", "policy"], queryFn: aiApi.policy });
  const [draft, setDraft] = useState<AiSettingsInput | null>(null);
  const saved = ai.data ? settingsFrom(ai.data.settings) : null;
  const value = draft ?? saved;

  const save = useMutation({
    mutationFn: (body: AiSettingsInput) => aiApi.saveProject(slug, body),
    onSuccess: (data, body) => {
      queryClient.setQueryData(["ai", "project", slug], data);
      queryClient.invalidateQueries({ queryKey: ["ai", "usage", slug] });
      setDraft((d) => (d !== null && same(d, body) ? null : d));    // edits made while saving are kept, not swallowed
    },
  });
  const addLocal = useMutation({
    mutationFn: (row: LocalRow) => aiApi.addKey({ provider: row.provider, label: row.name, key: "", base_url: row.base_url, model: row.model ?? "auto" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai", "keys"] });
      queryClient.invalidateQueries({ queryKey: ["ai", "project", slug] });   // the effective table changes with a new key
      document.getElementById("h-local")?.focus();
    },
  });

  if ((project.isError && !project.data) || (ai.isError && !ai.data)) {
    const e = project.isError ? project.error : ai.error;
    return (
      <p className="notice bad page-pad" role="alert">
        {notFound(e) ? "That project does not exist." : errorText(e, "The AI settings could not be loaded.")}
      </p>
    );
  }
  if (!project.data || !value || !ai.data) return <p className="muted page-pad">Loading…</p>;
  const p = project.data;
  const current = value;
  const names = Object.fromEntries((catalog.data?.providers ?? []).map((pr) => [pr.id, pr.name]));
  const labels = Object.fromEntries((catalog.data?.agents ?? []).map((a) => [a.agent, a.label]));
  const dirty = saved !== null && !same(current, saved);
  const providersProblem = catalog.isError ? "The provider list could not be loaded." : keys.isError ? "The stored keys could not be loaded." : policy.isError ? "The provider order could not be loaded." : null;

  function setAssignment(agent: string, tier: Tier | null) {
    const { [agent]: _dropped, ...rest } = current.assignments;
    setDraft({ ...current, assignments: tier ? { ...rest, [agent]: tier } : rest });
  }

  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">
            <Link to="/">Projects</Link> / <Link to={`/projects/${encodeURIComponent(slug)}`}>{p.name}</Link> / <b>AI</b>
          </div>
          <h1>AI for {p.name}</h1>
          <p className="sub">Which model helps each agent, what may leave this computer, and what it costs.</p>
        </div>
      </div>
      {ai.data.notice && <p className="notice warn">{ai.data.notice}</p>}
      {(project.isError || ai.isError) && <p className="notice warn">The page could not be refreshed; what you see may be a little old.</p>}

      <div className="grid g-two ai-grid">
        <AiForm
          value={current}
          dirty={dirty}
          catalog={catalog.data}
          catalogFailed={catalog.isError}
          effective={ai.data.effective}
          names={names}
          save={save}
          onChange={setDraft}
          onAssignment={setAssignment}
          onSubmit={() => save.mutate(current)}
        />
        <div className="stack">
          <section className="card" aria-labelledby="h-usage">
            <h2 id="h-usage">This month's spend</h2>
            {usage.data ? <UsageMeter usage={usage.data} labels={labels} /> : usage.isError ? <p className="notice bad">The usage figures could not be loaded.</p> : <p className="muted">Loading…</p>}
          </section>
          <LocalCard rows={local.data} probeFailed={local.isError} keys={keys.data} keysFailed={keys.isError} onUse={(row) => addLocal.mutate(row)} busy={addLocal.isPending} addError={addLocal.error} />
        </div>
      </div>

      <section className="card mt-4" aria-labelledby="h-providers">
        <h2 id="h-providers" tabIndex={-1}>
          Cloud providers and keys
        </h2>
        {providersProblem ? (
          <p className="notice bad">{providersProblem} Reload the page to try again.</p>
        ) : catalog.data && policy.data && keys.data ? (
          <Providers keys={keys.data} catalog={catalog.data} policy={policy.data} />
        ) : (
          <p className="muted">Loading…</p>
        )}
      </section>
    </>
  );
}
