import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "./lib/api";
import { Shell } from "./components/Shell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { SignIn } from "./pages/SignIn";
import { Projects } from "./pages/Projects";
import { Project } from "./pages/Project";
import { Live } from "./pages/Live";
import { Requirements } from "./pages/Requirements";
import { NewProject } from "./pages/wizard/NewProject";
import { LivePicker } from "./pages/LivePicker";
import { AiSettings } from "./pages/ai/AiSettings";

// The gate pages load with their route (M1.4): most visits never open them.
const Questions = lazy(() => import("./pages/gates/Questions").then((m) => ({ default: m.Questions })));
const TestPlan = lazy(() => import("./pages/gates/TestPlan").then((m) => ({ default: m.TestPlan })));
const Defects = lazy(() => import("./pages/gates/Defects").then((m) => ({ default: m.Defects })));
const ChangeLog = lazy(() => import("./pages/gates/ChangeLog").then((m) => ({ default: m.ChangeLog })));
const Visual = lazy(() => import("./pages/gates/Visual").then((m) => ({ default: m.Visual })));
const Heals = lazy(() => import("./pages/gates/Heals").then((m) => ({ default: m.Heals })));
const LOADING = <p className="muted page-pad" role="status">Loading…</p>;

/** Every page inside the Shell: a page that cannot load (its file went away after an update, or it throws) shows a
 *  message in place and the navigation stays; moving to another page tries again. */
export function PageFrame({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return (
    <ErrorBoundary resetKey={pathname} message="This page could not be loaded. Reload the page: AgentQA may have been updated.">
      <Suspense fallback={LOADING}>{children}</Suspense>
    </ErrorBoundary>
  );
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    throwOnError: (error) => !(error instanceof ApiError && error.status === 401),
  });
}

function RequireSignIn({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) return <p className="muted page-pad">Checking your session…</p>;
  if (!me.data) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route
        path="/*"
        element={
          <RequireSignIn>
            <Shell>
              <PageFrame>
                <Routes>
                  <Route index element={<Projects />} />
                  <Route path="projects/new" element={<NewProject />} />
                  <Route path="projects/:slug" element={<Project />} />
                  <Route path="projects/:slug/requirements" element={<Requirements />} />
                  <Route path="projects/:slug/questions" element={<Questions />} />
                  <Route path="projects/:slug/plan" element={<TestPlan />} />
                  <Route path="projects/:slug/defects" element={<Defects />} />
                  <Route path="projects/:slug/changes" element={<ChangeLog />} />
                  <Route path="projects/:slug/visual" element={<Visual />} />
                  <Route path="projects/:slug/heals" element={<Heals />} />
                  <Route path="projects/:slug/live" element={<Live />} />
                  <Route path="projects/:slug/ai" element={<AiSettings />} />
                  <Route path="live" element={<LivePicker />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </PageFrame>
            </Shell>
          </RequireSignIn>
        }
      />
    </Routes>
  );
}
