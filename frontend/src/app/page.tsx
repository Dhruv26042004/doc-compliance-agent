"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Health = {
  status: "ok" | "degraded";
  database: { connected: boolean; pgvector?: boolean; error?: string };
};

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError("API unreachable"));
  }, []);

  const rows: [string, boolean | undefined][] = [
    ["API", health !== null],
    ["Database", health?.database.connected],
    ["pgvector", health?.database.pgvector],
  ];

  return (
    <main className="mx-auto max-w-xl px-4 py-16">
      <h1 className="text-2xl font-semibold">Document Compliance</h1>
      <p className="mt-2 text-sm text-neutral-500">
        Contracts checked against a numbered policy, with every decision tied to a rule.
      </p>

      <section className="mt-10 rounded-lg border border-neutral-200 dark:border-neutral-800">
        <h2 className="border-b border-neutral-200 px-4 py-3 text-sm font-medium dark:border-neutral-800">
          System status
        </h2>
        <ul>
          {rows.map(([label, ok]) => (
            <li key={label} className="flex justify-between px-4 py-3 text-sm">
              <span>{label}</span>
              <span className={ok ? "text-green-600" : "text-red-600"}>
                {health === null && !error ? "checking…" : ok ? "up" : "down"}
              </span>
            </li>
          ))}
        </ul>
        {error && <p className="px-4 pb-3 text-sm text-red-600">{error}</p>}
      </section>
    </main>
  );
}
