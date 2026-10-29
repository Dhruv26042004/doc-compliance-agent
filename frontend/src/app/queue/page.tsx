"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Policy, type QueueItem } from "@/lib/api";
import { proposal, ROUTE_REASON } from "@/lib/display";

export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [rule, setRule] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.policy().then(setPolicy).catch(() => {});
  }, []);

  useEffect(() => {
    setItems(null);
    api
      .queue(rule || undefined)
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the queue"));
  }, [rule]);

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Review queue</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Decisions the system routed to a human. Each one becomes a labeled example once reviewed.
          </p>
        </div>
        <select
          value={rule}
          onChange={(e) => setRule(e.target.value)}
          className="rounded-md border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
        >
          <option value="">All rules</option>
          {policy?.rules.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id} {r.title}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="mt-6 text-sm text-red-700 dark:text-red-300">{error}</p>}
      {items === null && !error && <p className="mt-8 text-sm text-neutral-500">Loading…</p>}
      {items?.length === 0 && (
        <p className="mt-8 rounded-lg border border-dashed border-neutral-300 px-4 py-10 text-center text-sm text-neutral-500 dark:border-neutral-700">
          Nothing waiting for review.
        </p>
      )}

      <ul className="mt-6 space-y-3">
        {items?.map((d) => (
          <li key={d.id}>
            <Link
              href={`/documents/${d.document_id}?decision=${d.id}`}
              className="block rounded-lg border border-neutral-200 p-4 hover:border-neutral-400 dark:border-neutral-800 dark:hover:border-neutral-600"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className="font-mono text-xs text-neutral-500">{d.rule_id}</span>
                <span className="font-medium">{proposal(d)}</span>
                <span className="text-neutral-500">· {ROUTE_REASON[d.route_reason] ?? d.route_reason}</span>
                {d.confidence !== null && <span className="text-neutral-500">· confidence {d.confidence.toFixed(2)}</span>}
                <span className="ml-auto text-xs text-neutral-500">
                  {d.filename}
                  {d.clause_idx !== null && ` · clause ${d.clause_idx + 1}`}
                </span>
              </div>
              {(d.quote || d.clause_text) && (
                <p className="mt-2 line-clamp-2 text-sm text-neutral-600 dark:text-neutral-400">
                  {d.quote ? `“${d.quote}”` : d.clause_text}
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
