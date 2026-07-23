import React from "react";

/**
 * The section hero banner every console page leads with — a dark gradient panel carrying the
 * page's eyebrow, title, and one-line purpose, with an optional actions slot on the right and a
 * status line beneath it. Matches the reference console's per-section header.
 */
export default function PageHero({ eyebrow, title, sub, actions, status }: {
  eyebrow: string;
  title: React.ReactNode;
  sub?: React.ReactNode;
  actions?: React.ReactNode;
  status?: React.ReactNode;
}) {
  return (
    <section className="hero-banner">
      <div className="hero-banner-in">
        <div className="hero-banner-copy">
          <div className="hero-banner-eyebrow"><i />{eyebrow}</div>
          <h1>{title}</h1>
          {sub && <p>{sub}</p>}
        </div>
        {actions && <div className="hero-banner-actions">{actions}</div>}
      </div>
      {status && <div className="hero-banner-status">{status}</div>}
    </section>
  );
}
