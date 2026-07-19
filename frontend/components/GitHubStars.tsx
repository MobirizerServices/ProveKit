"use client";

import { useEffect, useState } from "react";

const REPO = "MobirizerServices/ProveKit";

// A "Star on GitHub" button that shows the live star count. Fails gracefully to a plain
// button if the (unauthenticated, public) GitHub API call doesn't return.
export default function GitHubStars({ className = "btn btn-ghost lp-btn" }: { className?: string }) {
  const [stars, setStars] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`https://api.github.com/repos/${REPO}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d && typeof d.stargazers_count === "number") setStars(d.stargazers_count); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  const label = stars == null ? "Star on GitHub" : `★ Star · ${stars.toLocaleString()}`;
  return (
    <a href={`https://github.com/${REPO}`} target="_blank" rel="noreferrer" className={className}>{label}</a>
  );
}
