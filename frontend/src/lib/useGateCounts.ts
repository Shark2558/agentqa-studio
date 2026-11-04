import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { gatePollMs } from "./gates";
import { gatesApi } from "./gatesApi";

/** The gate counts behind the navigation badges, the Project page's "What needs you", the gate pages' "a run is
 *  going" and the Live View's gates. `slug` null (outside a project, or an older run in the Live View) asks nothing.
 *  One query per project, shared; how often it asks is `gatePollMs`. */
export function useGateCounts(slug: string | null) {
  return useQuery({
    queryKey: ["gates", slug],
    queryFn: () => gatesApi.counts(slug ?? ""),
    enabled: slug !== null,
    refetchInterval: (q) => gatePollMs(q.state.data, q.state.error),
  });
}

/** When a run that was going has finished, reload what it may have changed (a re-plan rewrites questions and cases,
 *  a run adds defects): the page must not keep showing the picture from before the run. `keys` is a module constant. */
export function useRefreshWhenRunEnds(slug: string, running: boolean | undefined, keys: readonly string[]) {
  const queryClient = useQueryClient();
  const was = useRef(running);
  useEffect(() => {
    if (was.current && running === false) for (const key of keys) queryClient.invalidateQueries({ queryKey: [key, slug] });
    was.current = running;
  }, [running, slug, keys, queryClient]);
}
