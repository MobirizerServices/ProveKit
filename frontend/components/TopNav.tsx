"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, EnvironmentT, Me } from "@/lib/api";
import EnvironmentModal from "./EnvironmentModal";

const LINKS = [
  { href: "/", label: "Console" },
  { href: "/flows", label: "Flows" },
  { href: "/prompts", label: "Prompts" },
  { href: "/deployments", label: "Deployments" },
  { href: "/api-keys", label: "API Keys" },
];

export default function TopNav() {
  const path = usePathname();
  const router = useRouter();
  const [envs, setEnvs] = useState<EnvironmentT[]>([]);
  const [envModal, setEnvModal] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [menu, setMenu] = useState(false);
  const [down, setDown] = useState(false);
  const load = () => api.environments().then(setEnvs).catch(() => {});
  useEffect(() => { load(); api.me().then(setMe).catch(() => {}); }, []);
  // Poll backend health so a dropped API surfaces a banner instead of silent failures.
  useEffect(() => {
    let alive = true;
    const check = () => api.health().then((ok) => alive && setDown(!ok));
    check(); const t = setInterval(check, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const logout = async () => { try { await api.logout(); } catch {} router.push("/login"); };
  const isLocal = me?.auth_provider === "local";

  const active = envs.find((e) => e.is_active);
  const setActive = async (id: string) => {
    const e = envs.find((x) => x.id === +id);
    if (id === "none") { const cur = envs.find((x) => x.is_active); if (cur) await api.updateEnvironment(cur.id, { name: cur.name, variables: cur.variables, is_active: false }); }
    else if (e) await api.updateEnvironment(e.id, { name: e.name, variables: e.variables, is_active: true });
    load();
  };
  const is = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <>
    {down && <div className="down-banner" role="status">⚠ Can’t reach the ProveKit backend. Retrying… — check that it’s running on the API port.</div>}
    <div className="topbar">
      <div className="brand"><span className="logo">◇</span>Prove<b>Kit</b></div>
      <nav className="topnav">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={`tn-link ${is(l.href) ? "on" : ""}`}>{l.label}</Link>
        ))}
      </nav>
      <div className="env-picker">
        <span className="tb-hint">env</span>
        <select value={active?.id ?? "none"} onChange={(e) => setActive(e.target.value)}
          style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "6px 10px", fontSize: 12.5 }}>
          <option value="none">No environment</option>
          {envs.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
        </select>
        <button className="btn btn-ghost btn-sm" onClick={() => setEnvModal(true)}>⚙</button>
      </div>
      {me && !isLocal && (
        <div className="tb-user" onClick={() => setMenu((m) => !m)}>
          <span className="tb-avatar" title={me.email}>{(me.name || me.email)[0]?.toUpperCase()}</span>
          {menu && (
            <div className="tb-menu" onMouseLeave={() => setMenu(false)}>
              <div className="tb-menu-email">{me.email}</div>
              <button onClick={logout}>Sign out</button>
            </div>
          )}
        </div>
      )}
      {envModal && <EnvironmentModal environments={envs} onChanged={load} onClose={() => setEnvModal(false)} />}
    </div>
    </>
  );
}
