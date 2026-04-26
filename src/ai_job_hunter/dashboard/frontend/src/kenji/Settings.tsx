import { useEffect, useState } from "react";

export function Settings() {
  const [data, setData] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div style={{ padding: "32px 40px" }}>
      <h2 style={{ fontFamily: "var(--font-display)", marginBottom: "1rem" }}>Settings</h2>
      <p style={{ color: "var(--outline)", marginBottom: "1.5rem" }}>
        Full settings UI coming soon. Backend data below for verification.
      </p>
      {error && <pre style={{ color: "var(--error)" }}>{error}</pre>}
      {data && (
        <pre className="mono" style={{ background: "var(--primary-tint)", padding: "1rem", borderRadius: "var(--r)" }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}
