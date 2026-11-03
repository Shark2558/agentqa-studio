import { Plus, Trash } from "@phosphor-icons/react";
import type { RoleInput } from "../../lib/api";

export const METHODS: Record<string, string> = {
  password: "Username and password",
  password_otp: "Username, password and OTP",
  mobile_otp: "Mobile number and OTP",
  email_otp: "Email and OTP",
  mfa: "Password and authenticator app",
  sso: "Single sign-on",
};
export const OTP_SOURCES: Record<string, string> = {
  ask: "Ask me on screen (live portals)",
  inbox: "AgentQA mock inbox (test environments)",
  fixed: "A fixed test OTP",
};
const NEEDS_OTP = new Set(["password_otp", "mobile_otp", "email_otp"]);

type Props = {
  noLogin: boolean;
  roles: RoleInput[];
  onNoLogin: (value: boolean) => void;
  onRole: (index: number, role: RoleInput) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
};

/** Step 3: one test account per kind of user. Passwords go straight to the encrypted vault and never come back. */
export function StepAccounts({ noLogin, roles, onNoLogin, onRole, onAdd, onRemove }: Props) {
  return (
    <>
      <label className="check">
        <input type="checkbox" checked={noLogin} onChange={(e) => onNoLogin(e.target.checked)} />
        No login needed — the application is public
      </label>
      {!noLogin && (
        <>
          {roles.map((r, i) => (
            <fieldset className="card flat role" key={r.uid ?? i}>
              <legend>Kind of user {i + 1}</legend>
              <div className="grid g-role">
                <div>
                  <label htmlFor={`role-${i}`}>Role name</label>
                  <input id={`role-${i}`} placeholder="clerk" value={r.role} onChange={(e) => onRole(i, { ...r, role: e.target.value })} />
                </div>
                <div>
                  <label htmlFor={`login-option-${i}`}>Login button text</label>
                  <input id={`login-option-${i}`} placeholder="Department Login" value={r.login_option} onChange={(e) => onRole(i, { ...r, login_option: e.target.value })} />
                </div>
                <div>
                  <label htmlFor={`method-${i}`}>How they sign in</label>
                  <select id={`method-${i}`} value={r.method} onChange={(e) => onRole(i, { ...r, method: e.target.value })}>
                    {Object.entries(METHODS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>
                {r.method === "mobile_otp" ? (
                  <div>
                    <label htmlFor={`mobile-${i}`}>Mobile number</label>
                    <input id={`mobile-${i}`} inputMode="tel" value={r.mobile ?? ""} onChange={(e) => onRole(i, { ...r, mobile: e.target.value })} />
                  </div>
                ) : r.method === "email_otp" ? (
                  <div>
                    <label htmlFor={`email-${i}`}>Email</label>
                    <input id={`email-${i}`} type="email" value={r.email ?? ""} onChange={(e) => onRole(i, { ...r, email: e.target.value })} />
                  </div>
                ) : (
                  <>
                    <div>
                      <label htmlFor={`username-${i}`}>Username</label>
                      <input id={`username-${i}`} autoComplete="off" value={r.username ?? ""} onChange={(e) => onRole(i, { ...r, username: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`password-${i}`}>Password</label>
                      <input id={`password-${i}`} type="password" autoComplete="new-password" value={r.password ?? ""} onChange={(e) => onRole(i, { ...r, password: e.target.value })} />
                    </div>
                  </>
                )}
                {NEEDS_OTP.has(r.method) && (
                  <div>
                    <label htmlFor={`otp-${i}`}>Where the OTP comes from</label>
                    <select id={`otp-${i}`} value={r.otp_source ?? "ask"} onChange={(e) => onRole(i, { ...r, otp_source: e.target.value })}>
                      {Object.entries(OTP_SOURCES).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <div>
                  <label htmlFor={`aliases-${i}`}>Other names the documents use</label>
                  <input
                    id={`aliases-${i}`}
                    placeholder="Clerk, Front office"
                    value={(r.aliases ?? []).join(", ")}
                    onChange={(e) => onRole(i, { ...r, aliases: e.target.value.split(",").map((a) => a.trim()).filter(Boolean) })}
                  />
                </div>
              </div>
              {roles.length > 1 && (
                <button className="btn sm" type="button" onClick={() => onRemove(i)}>
                  <Trash aria-hidden="true" />
                  Remove
                </button>
              )}
            </fieldset>
          ))}
          <button className="btn" type="button" onClick={onAdd}>
            <Plus aria-hidden="true" />
            Another kind of user
          </button>
          <p className="muted small">Passwords are stored encrypted on this machine and never shown again. Use test accounts, not personal ones.</p>
        </>
      )}
    </>
  );
}
