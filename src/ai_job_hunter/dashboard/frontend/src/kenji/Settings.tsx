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
    <div style={{ padding: "2rem", fontFamily: "JetBrains Mono, monospace", fontSize: "0.85rem" }}>
      <h2 style={{ fontFamily: "Manrope, sans-serif", marginBottom: "1rem" }}>Settings</h2>
      <p style={{ color: "#5a6b68", marginBottom: "1.5rem" }}>
        Full settings UI coming soon. Backend data below for verification.
      </p>
      {error && <pre style={{ color: "red" }}>{error}</pre>}
      {data && <pre style={{ background: "#eef4f2", padding: "1rem", borderRadius: "8px" }}>{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}
