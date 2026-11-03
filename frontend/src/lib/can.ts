/** What the signed-in role may do (FR-LIVE-8). The server enforces it (403 `read_only` on every write from another
 *  role); the app only hides controls a Viewer could not use anyway. Team logins arrive in M2.1. */
export const WRITE_ROLES: ReadonlySet<string> = new Set(["owner", "tester"]);

export function canWrite(role: string | null | undefined): boolean {
  return typeof role === "string" && WRITE_ROLES.has(role);
}
