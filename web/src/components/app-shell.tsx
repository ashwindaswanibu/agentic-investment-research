"use client";
import {
  createContext,
  useContext,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowUpRight,
  BookOpen,
  FlaskConical,
  Layers3,
  LockKeyhole,
  Menu,
  Microscope,
  Radio,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import {
  parseCapabilities,
  parseWorkspaces,
  type Capabilities,
  type Workspace,
} from "@/lib/contracts";
import { useResource } from "@/lib/use-resource";
import { message, request } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ErrorNotice, Modal } from "./ui";

interface Environment {
  capabilities: Capabilities | null;
  workspaces: Workspace[];
  capabilityError: string | null;
  canWrite: boolean;
  refresh: () => Promise<void>;
}
const EnvironmentContext = createContext<Environment | null>(null);
export function useEnvironment() {
  const value = useContext(EnvironmentContext);
  if (!value) throw new Error("Missing environment context");
  return value;
}
const nav = [
  { href: "/", label: "Research", icon: Microscope },
  { href: "/experiments", label: "Experiments", icon: FlaskConical },
  { href: "/library", label: "Library", icon: BookOpen },
  { href: "/portfolio", label: "Paper portfolio", icon: Wallet },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const caps = useResource("/capabilities", parseCapabilities, 15_000);
  const spaces = useResource("/workspaces", parseWorkspaces);
  const [menu, setMenu] = useState(false),
    [settings, setSettings] = useState(false);
  const [token, setToken] = useState(""),
    [loginError, setLoginError] = useState<string | null>(null),
    [signingIn, setSigningIn] = useState(false);
  const authenticated = caps.data?.authenticated === true;
  const canWrite =
    !!caps.data &&
    !caps.data.read_only &&
    (!caps.data.authentication_required || authenticated);
  const current =
    nav.find((item) => item.href !== "/" && pathname.startsWith(item.href)) ||
    nav[0];
  async function login(e: FormEvent) {
    e.preventDefault();
    setSigningIn(true);
    setLoginError(null);
    try {
      await request("/session", () => true, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      setToken("");
      window.dispatchEvent(new Event("research-session-changed"));
      await caps.refresh();
    } catch (error) {
      setLoginError(message(error));
    } finally {
      setSigningIn(false);
    }
  }
  return (
    <EnvironmentContext.Provider
      value={{
        capabilities: caps.data,
        workspaces: spaces.data || [],
        capabilityError: caps.error,
        canWrite,
        refresh: caps.refresh,
      }}
    >
      <div className="app-shell">
        {menu && (
          <button
            className="nav-scrim"
            aria-label="Close navigation"
            onClick={() => setMenu(false)}
          />
        )}
        <aside className={`sidebar ${menu ? "sidebar-open" : ""}`}>
          <Link href="/" className="brand" onClick={() => setMenu(false)}>
            <span className="brand-mark">
              <Layers3 size={21} strokeWidth={1.6} />
            </span>
            <span>
              researchdesk<small>INVESTMENT RESEARCH</small>
            </span>
          </Link>
          <div className="sidebar-caption">WORKBENCH</div>
          <nav aria-label="Main navigation">
            {nav.map(({ href, label, icon: Icon }) => {
              const active =
                href === "/"
                  ? pathname === "/" || pathname.startsWith("/cases/")
                  : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`nav-link ${active ? "nav-link-active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setMenu(false)}
                >
                  <Icon size={18} />
                  {label}
                  {active && <span className="nav-active-dot" />}
                </Link>
              );
            })}
          </nav>
          <div className="sidebar-workspaces">
            <div className="sidebar-caption">SPECIALIST WORKSPACES</div>
            {spaces.data?.map((space) => (
              <Link
                key={space.id}
                href={`/?workspace=${encodeURIComponent(space.id)}`}
                className="workspace-link"
                onClick={() => setMenu(false)}
              >
                <span className="workspace-initial">
                  {space.name.slice(0, 1)}
                </span>
                <span>{space.name}</span>
              </Link>
            ))}
            {!spaces.data && (
              <p className="sidebar-note">
                {spaces.error
                  ? "Workspaces unavailable"
                  : "Connecting to workspaces…"}
              </p>
            )}
          </div>
          <div className="sidebar-bottom">
            <button
              className="environment-button"
              onClick={() => setSettings(true)}
            >
              <Settings2 size={17} />
              <span>
                Environment
                <small>
                  {caps.error
                    ? "Connection unavailable"
                    : caps.data?.provider.configured
                      ? caps.data.provider.name
                      : "Provider setup needed"}
                </small>
              </span>
              <ArrowUpRight size={14} />
            </button>
            <div className="sidebar-footer">Evidence before conclusions.</div>
          </div>
        </aside>
        <div className="app-main">
          <header className="topbar">
            <div className="topbar-location">
              <button
                className="icon-button mobile-menu"
                aria-label="Open navigation"
                onClick={() => setMenu(true)}
              >
                <Menu size={20} />
              </button>
              <span className="topbar-product">Workspace</span>
              <span className="breadcrumb-divider">/</span>
              <span>{current.label}</span>
            </div>
            <div className="topbar-actions">
              <span className="mode-pill">
                <ShieldCheck size={13} />
                Paper environment
              </span>
              {caps.data?.read_only && (
                <span className="read-only-pill">
                  <LockKeyhole size={12} />
                  Read only
                </span>
              )}
              {caps.data?.authentication_required &&
                !caps.data.read_only &&
                !authenticated && (
                  <button
                    className="button button-secondary button-small"
                    onClick={() => setSettings(true)}
                  >
                    Sign in
                  </button>
                )}
              <button
                className="icon-button environment-trigger"
                aria-label="Environment status"
                onClick={() => setSettings(true)}
              >
                <span
                  className={`connection-dot ${caps.error ? "connection-error" : caps.data ? "connection-ok" : ""}`}
                />
              </button>
            </div>
          </header>
          <main id="main-content">{children}</main>
          <footer className="app-footer">
            <span>
              Research is exploratory. Experiments and paper decisions are
              recorded separately.
            </span>
            <span>Paper execution only</span>
          </footer>
        </div>
      </div>
      {settings && (
        <Modal
          title="Research environment"
          onClose={() => {
            setSettings(false);
            setToken("");
          }}
        >
          <div className="modal-body">
            <p className="muted">
              Capabilities reported by the research service. Provider
              credentials remain on the server.
            </p>
            {caps.error && (
              <ErrorNotice onRetry={() => void caps.refresh()}>
                {caps.error}
              </ErrorNotice>
            )}
            {caps.data && (
              <>
                <dl className="environment-list">
                  <div>
                    <dt>Model provider</dt>
                    <dd>
                      {caps.data.provider.name} ·{" "}
                      {caps.data.provider.configured
                        ? "Configured"
                        : "Not configured"}
                    </dd>
                  </div>
                  <div>
                    <dt>Model</dt>
                    <dd className="mono">
                      {caps.data.provider.model || "Not configured"}
                    </dd>
                  </div>
                  <div>
                    <dt>Worker</dt>
                    <dd>
                      {caps.data.worker.active ? "Active" : "Not active"}
                      <small>
                        Last heartbeat:{" "}
                        {dateTime(caps.data.worker.last_seen_at)}
                      </small>
                    </dd>
                  </div>
                  <div>
                    <dt>Code isolation</dt>
                    <dd>
                      {caps.data.sandbox.available
                        ? "Available"
                        : "Unavailable"}
                      <small>{caps.data.sandbox.reason}</small>
                    </dd>
                  </div>
                  <div>
                    <dt>Access</dt>
                    <dd>
                      {caps.data.read_only
                        ? "Read-only deployment"
                        : canWrite
                          ? "Operator"
                          : "Sign-in required"}
                    </dd>
                  </div>
                  <div>
                    <dt>Registered tools</dt>
                    <dd>{caps.data.tools.length}</dd>
                  </div>
                </dl>
                {caps.data.limitations.length > 0 && (
                  <div className="environment-limitations">
                    <h3>Current limitations</h3>
                    <ul>
                      {caps.data.limitations.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {!caps.data.read_only &&
                  caps.data.authentication_required &&
                  !authenticated && (
                    <form onSubmit={login} className="auth-form">
                      <label htmlFor="operator-token">Operator token</label>
                      <input
                        id="operator-token"
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        autoComplete="off"
                        required
                        placeholder="Enter the server's operator token"
                      />
                      <p className="field-help">
                        Used to establish an HTTP-only session. The token is not
                        stored in browser storage.
                      </p>
                      {loginError && <ErrorNotice>{loginError}</ErrorNotice>}
                      <button
                        className="button button-primary"
                        disabled={signingIn}
                      >
                        {signingIn ? "Signing in…" : "Sign in"}
                      </button>
                    </form>
                  )}
                {caps.data.authentication_required && authenticated && (
                  <button
                    className="button button-secondary"
                    onClick={async () => {
                      try {
                        await request("/session", () => true, {
                          method: "DELETE",
                        });
                        window.dispatchEvent(
                          new Event("research-session-changed"),
                        );
                      } catch (error) {
                        setLoginError(message(error));
                      }
                    }}
                  >
                    Sign out
                  </button>
                )}
              </>
            )}
            <button
              className="button button-secondary"
              onClick={() => void caps.refresh()}
            >
              <RefreshCw size={15} />
              Refresh status
            </button>
          </div>
        </Modal>
      )}
    </EnvironmentContext.Provider>
  );
}
