import { Navigate, Route, Routes, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "./lib/api";
import { Shell } from "./components/Shell";
import { SignIn } from "./pages/SignIn";
import { Projects } from "./pages/Projects";
import { Project } from "./pages/Project";
import { Live } from "./pages/Live";
import { Requirements } from "./pages/Requirements";
import { NewProject } from "./pages/wizard/NewProject";
import { LivePicker } from "./pages/LivePicker";

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
              <Routes>
                <Route index element={<Projects />} />
                <Route path="projects/new" element={<NewProject />} />
                <Route path="projects/:slug" element={<Project />} />
                <Route path="projects/:slug/requirements" element={<Requirements />} />
                <Route path="projects/:slug/live" element={<Live />} />
                <Route path="live" element={<LivePicker />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Shell>
          </RequireSignIn>
        }
      />
    </Routes>
  );
}
