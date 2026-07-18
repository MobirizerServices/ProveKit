"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Me } from "@/lib/api";

const LINKS = [
  { href: "/traces", label: "Traces" },
  { href: "/api-keys", label: "Project keys" },
];

export default function TopNav() {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [menu, setMenu] = useState(false);
  const [down, setDown] = useState(false);
  useEffect(() => { api.me().then(setMe).catch(() => {}); }, []);
  // Poll backend health so a dropped API surfaces a banner instead of silent failures.
  useEffect(() => {
    let alive = true;
    const check = () => api.health().then((ok) => alive && setDown(!ok));
    check(); const t = setInterval(check, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const logout = async () => { try { await api.logout(); } catch {} router.push("/login"); };
  const isLocal = me?.auth_provider === "local";
  const is = (href: string) => path.startsWith(href);

  return (
    <>
      {down && <div className="down-banner" role="status">⚠ Can’t reach the ProveKit backend. Retrying…</div>}
      <div className="topbar">
        <Link href="/traces" className="brand" style={{ textDecoration: "none" }}>
          <span className="logo">◇</span>Prove<b>Kit</b>
        </Link>
        <nav className="topnav">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={`tn-link ${is(l.href) ? "on" : ""}`}>{l.label}</Link>
          ))}
        </nav>
        <div style={{ flex: 1 }} />
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
      </div>
    </>
  );
}
