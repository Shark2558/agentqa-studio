import { useMutation } from "@tanstack/react-query";
import { Globe } from "@phosphor-icons/react";
import { ApiError, api } from "../../lib/api";
import type { Environment } from "../../lib/wizard";

const ENVIRONMENTS: Environment[] = ["Development", "Test / QA", "UAT", "Staging", "Production"];

type Props = {
  name: string;
  url: string;
  environment: Environment;
  locked: boolean;
  onField: (field: "name" | "url", value: string) => void;
  onEnvironment: (value: Environment) => void;
};

/** Step 1: name, address, environment, and the reachability / login check (FR-ONB-5). */
export function StepBasics({ name, url, environment, locked, onField, onEnvironment }: Props) {
  const check = useMutation({ mutationFn: () => api.preflight(url) });
  const result = check.data;
  const error = check.error instanceof ApiError ? check.error : null;

  return (
    <>
      <label htmlFor="w-name">Project name</label>
      <input id="w-name" required maxLength={80} value={name} readOnly={locked} onChange={(e) => onField("name", e.target.value)} />
      <label htmlFor="w-url">Application address</label>
      <div className="row">
        <input
          id="w-url"
          type="url"
          required
          placeholder="https://uat.example.gov.in"
          value={url}
          readOnly={locked}
          onChange={(e) => {
            check.reset();                                   // a verdict belongs to the address it was run on
            onField("url", e.target.value);
          }}
        />
        <button className="btn" type="button" onClick={() => check.mutate()} disabled={!/^https?:\/\/[^\s/]+/.test(url) || check.isPending}>
          <Globe aria-hidden="true" />
          {check.isPending ? "Checking…" : "Check the address"}
        </button>
      </div>
      {locked && <p className="muted small">The project is created; change its name or address later from the project page.</p>}
      {result && (
        <p className={`notice ${result.reachable && !result.fix ? "ok" : "warn"}`} role="status">
          {result.reachable ? `Reachable (answered ${result.status}). ` : "Not reachable. "}
          {result.login_detected
            ? result.login_url
              ? `A login page was found at ${result.login_url}; add the accounts in step 3.`
              : "A login button was found on the first page; add the accounts in step 3."
            : result.reachable
              ? "No login page was seen on the first page; if people sign in, add their accounts in step 3."
              : ""}
          {result.fix && <> {result.fix}</>}
        </p>
      )}
      {error && (
        <p className="notice bad" role="alert">
          {error.message}
        </p>
      )}
      <label htmlFor="w-env">Environment</label>
      <select id="w-env" value={environment} disabled={locked} onChange={(e) => onEnvironment(e.target.value as Environment)}>
        {ENVIRONMENTS.map((env) => (
          <option key={env} value={env}>
            {env}
          </option>
        ))}
      </select>
      <p className="muted small">
        {environment === "Production"
          ? "Production is read-only: AgentQA will look but never submit forms, run workflows, attack or load the site."
          : "On a test environment AgentQA fills forms, runs workflows and tries unsafe inputs."}
      </p>
    </>
  );
}
