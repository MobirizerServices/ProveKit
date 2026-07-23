"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getProjectId, Me, Project, setProjectId } from "@/lib/api";

/**
 * The authenticated app shell: a left sidebar (brand, project switcher, grouped nav) and a top
 * bar (breadcrumb, global search, user). Every console page renders inside it, replacing the
 * old horizontal TopNav.
 *
 * The nav mirrors the reference console's information architecture. Items map to the real
 * routes that back them; nothing here links somewhere that doesn't exist.
 */
type NavItem = { href: string; label: string; icon: string; badge?: string };
type NavGroup = { items: NavItem[] };

const NAV: NavGroup[] = [
  { items: [
    { href: "/dashboard", label: "Overview", icon: "gauge" },
    { href: "/flows", label: "Agent Flows", icon: "flow" },
    { href: "/traces", label: "Traces", icon: "trace" },
    { href: "/sessions", label: "Sessions", icon: "chat" },
    { href: "/playground", label: "Playground", icon: "play" },
  ] },
  { items: [
    { href: "/datasets", label: "Datasets", icon: "data" },
    { href: "/experiments", label: "Experiments", icon: "flask" },
    { href: "/evaluations", label: "Evaluations", icon: "shield" },
    { href: "/evaluators", label: "Evaluators", icon: "spark" },
  ] },
  { items: [
    { href: "/prompts", label: "Prompts", icon: "cmd" },
    { href: "/automations", label: "Automations", icon: "bolt" },
    { href: "/api-keys", label: "Project keys", icon: "key" },
  ] },
];

export default function ConsoleShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projOpen, setProjOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [down, setDown] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => { api.me().then(setMe).catch(() => {}); }, []);
  useEffect(() => { api.projects().then(setProjects).catch(() => {}); }, []);
  useEffect(() => {
    let alive = true;
    const check = () => api.health().then((ok) => alive && setDown(!ok));
    check(); const t = setInterval(check, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const curId = getProjectId();
  const current = projects.find((p) => String(p.id) === curId) || projects.find((p) => p.is_default) || projects[0];
  const switchTo = (id: number) => { setProjectId(id); window.location.reload(); };
  const logout = async () => { try { await api.logout(); } catch {} router.push("/login"); };
  const isLocal = me?.auth_provider === "local";
  const on = (href: string) => path === href || path.startsWith(href + "/");

  // Breadcrumb from the active nav item (falls back to a title-cased path segment).
  const active = NAV.flatMap((g) => g.items).find((i) => on(i.href));
  const crumb = active?.label
    || (path === "/admin" ? "Admin"
        : path === "/settings" ? "Settings"
        : (path.split("/")[1] || "").replace(/^\w/, (c) => c.toUpperCase()));

  return (
    <div className="cs">
      {down && <div className="down-banner cs-down" role="status">⚠ Can’t reach the ProveKit backend. Retrying…</div>}

      <aside className={`cs-side ${mobileOpen ? "open" : ""}`}>
        <Link href="/dashboard" className="cs-brand" onClick={() => setMobileOpen(false)}>
          <span className="cs-mark">///</span>ProveKit
        </Link>

        {projects.length > 0 && (
          <div className="cs-proj" onMouseLeave={() => setProjOpen(false)}>
            <button className="cs-proj-btn" onClick={() => setProjOpen((o) => !o)}>
              <span className="cs-proj-tile">{(current?.name || "P")[0].toUpperCase()}</span>
              <span className="cs-proj-name">
                <b>{current?.name || "Project"}</b>
                <small>{current?.role || "workspace"}</small>
              </span>
              <span className="cs-proj-caret">▾</span>
            </button>
            {projOpen && (
              <div className="cs-proj-menu">
                {projects.map((p) => (
                  <button key={p.id} className={`cs-proj-item ${current?.id === p.id ? "on" : ""}`}
                    onClick={() => switchTo(p.id)}>
                    <span>{p.name}</span>
                    <span className="cs-proj-role">{p.role}{p.is_default ? " · default" : ""}</span>
                  </button>
                ))}
                <Link href="/settings" className="cs-proj-manage" onClick={() => setProjOpen(false)}>Manage projects →</Link>
              </div>
            )}
          </div>
        )}

        <nav className="cs-nav">
          {NAV.map((group, gi) => (
            <div key={gi} className="cs-nav-group">
              {group.items.map((it) => (
                <Link key={it.href} href={it.href} className={`cs-link ${on(it.href) ? "on" : ""}`}
                  onClick={() => setMobileOpen(false)}>
                  <Icon name={it.icon} />
                  <span>{it.label}</span>
                  {it.badge && <em className="cs-badge">{it.badge}</em>}
                </Link>
              ))}
            </div>
          ))}
        </nav>

        <div className="cs-foot">
          {me?.is_superuser && (
            <Link href="/admin" className={`cs-link ${on("/admin") ? "on" : ""}`} onClick={() => setMobileOpen(false)}>
              <Icon name="building" /><span>Admin console</span><em className="cs-badge ops">OPS</em>
            </Link>
          )}
          <Link href="/settings" className={`cs-link ${on("/settings") ? "on" : ""}`} onClick={() => setMobileOpen(false)}>
            <Icon name="cog" /><span>Settings</span>
          </Link>
        </div>
      </aside>

      {mobileOpen && <div className="cs-scrim" onClick={() => setMobileOpen(false)} />}

      <div className="cs-main">
        <header className="cs-top">
          <button className="cs-burger" aria-label="Menu" onClick={() => setMobileOpen((o) => !o)}>☰</button>
          <div className="cs-crumb"><span className="cs-crumb-proj">{current?.name || "Workspace"}</span><span>/</span><b>{crumb}</b></div>
          <div className="cs-search" role="search">
            <Icon name="search" />
            <input placeholder="Search traces, flows, prompts…"
              onKeyDown={(e) => { if (e.key === "Enter") { const q = (e.target as HTMLInputElement).value.trim(); if (q) router.push(`/traces?q=${encodeURIComponent(q)}`); } }} />
            <kbd>⌘K</kbd>
          </div>
          {me && !isLocal ? (
            <div className="cs-user" onClick={() => setUserOpen((o) => !o)}>
              <span className="cs-avatar" title={me.email}>{(me.name || me.email)[0]?.toUpperCase()}</span>
              {userOpen && (
                <div className="cs-user-menu" onMouseLeave={() => setUserOpen(false)}>
                  <div className="cs-user-email">{me.email}</div>
                  <button onClick={logout}>Sign out</button>
                </div>
              )}
            </div>
          ) : (
            <span className="cs-local" title="Local self-host mode">Local</span>
          )}
        </header>

        <div className="cs-content">{children}</div>
      </div>
    </div>
  );
}

const PATHS: Record<string, string> = {
  gauge: "M2.5 11a5.5 5.5 0 1 1 11 0M8 11l3-3.2",
  flow: "M8 2a2 2 0 0 1 2 2v1h2a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2ZM6 9h.01M10 9h.01",
  trace: "M2 8h2.5l1.5-4 2 8 2-6 1.5 2H14",
  chat: "M3 4.5h10v6H7l-3 2.5v-2.5H3v-6Z",
  play: "M5 3.5v9l8-4.5-8-4.5Z",
  data: "M2.5 4.5h11v3.5h-11V4.5Zm0 5h11V13h-11V9.5Z",
  flask: "M6.5 2v4L3 12.5A1.2 1.2 0 0 0 4 14.5h8a1.2 1.2 0 0 0 1-2L9.5 6V2M5.5 2h5",
  shield: "M8 2 3 4v4c0 3 2.2 5.4 5 6 2.8-.6 5-3 5-6V4L8 2Zm-2 6 1.5 1.5L10.5 6.5",
  spark: "M8 2l1.6 3.9L13.5 7.5 9.6 9.1 8 13l-1.6-3.9L2.5 7.5l3.9-1.6L8 2Z",
  cmd: "M5 5.5A1.5 1.5 0 1 1 6.5 7H5V5.5ZM11 5.5A1.5 1.5 0 1 0 9.5 7H11V5.5ZM5 10.5A1.5 1.5 0 1 0 6.5 9H5v1.5ZM11 10.5A1.5 1.5 0 1 1 9.5 9H11v1.5ZM6.5 7h3v2h-3z",
  bolt: "M9 2 4 9h3l-1 5 5-7H8l1-5Z",
  key: "M9.5 2a4 4 0 0 0-3.8 5.2L2 11v2.5h2.5V12H6v-1.5h1.5l.3-.3A4 4 0 1 0 9.5 2Zm1.5 3.5h.01",
  building: "M4 14V3h8v11M6.5 6h.01M9.5 6h.01M6.5 9h.01M9.5 9h.01M7 14v-2.5h2V14",
  cog: "M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5ZM8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8 3.4 3.4",
  search: "M7.2 12a4.8 4.8 0 1 0 0-9.6 4.8 4.8 0 0 0 0 9.6ZM11 11l3 3",
};

function Icon({ name }: { name: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden className="cs-ico">
      <path d={PATHS[name] || PATHS.trace} stroke="currentColor" strokeWidth="1.35"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
