import { useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../lib/api";

export function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  const login = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/sign-in" ? from : "/", { replace: true });
    },
  });

  const error = login.error instanceof ApiError ? login.error : null;
  const ownerMissing = health.data && !health.data.owner_configured;

  return (
    <main className="sign-in">
      <form
        className="card sign-in-card"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
        aria-labelledby="sign-in-title"
      >
        <div className="brand">
          <span className="mark" aria-hidden="true">AQ</span>
          <span>
            <span className="brand-name">AgentQA Studio</span>
            <span className="brand-tag">Agents that test like people</span>
          </span>
        </div>
        <h1 id="sign-in-title">Sign in</h1>
        {ownerMissing && (
          <p className="notice warn" role="status">
            No owner account yet. In a terminal run <code>python -m agentqa owner-set</code>, then restart the dashboard.
          </p>
        )}
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && (
          <p className="notice bad" role="alert">
            {error.code === "rate_limited" ? "Too many failed sign-ins. Wait a while and try again." : error.message}
          </p>
        )}
        <button className="btn primary" type="submit" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
