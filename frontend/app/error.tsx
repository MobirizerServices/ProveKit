"use client";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="err-page">
      <div className="err-card">
        <div className="err-icon">⚠</div>
        <h2>Something went wrong</h2>
        <p>{error.message || "An unexpected error occurred."}</p>
        <div className="err-actions">
          <button className="btn btn-run" onClick={reset}>Try again</button>
          <a className="btn btn-ghost" href="/">Go home</a>
        </div>
      </div>
    </div>
  );
}
