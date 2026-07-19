"use client";

// Reusable loading placeholder with a subtle shimmer. Use <Skeleton w="60%" h={16} /> or
// compose a few. Keeps loading states consistent across the app.
export function Skeleton({ w = "100%", h = 14, r = 6, mt = 0 }: { w?: string | number; h?: number; r?: number; mt?: number }) {
  return (
    <div style={{
      width: typeof w === "number" ? `${w}px` : w, height: h, borderRadius: r, marginTop: mt,
      background: "var(--panel-2)", animation: "pk-shimmer 1.2s ease-in-out infinite",
    }} />
  );
}

// Drop this once per page that uses <Skeleton> to define the keyframes.
export function SkeletonStyles() {
  return <style jsx global>{`@keyframes pk-shimmer { 0%,100% { opacity: .5 } 50% { opacity: .85 } }`}</style>;
}

// A grid of N stat-card skeletons (dashboard) or rows (tables).
export function CardGridSkeleton({ n = 6 }: { n?: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12 }}>
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 }}>
          <Skeleton w="50%" h={10} />
          <Skeleton w="70%" h={22} mt={10} />
        </div>
      ))}
      <SkeletonStyles />
    </div>
  );
}
