"use client";

import { useState } from "react";

import { api, type Decision, type Rule } from "@/lib/api";
import { proposal, ROUTE_REASON, TONE_CLASSES, tone } from "@/lib/display";

type Props = {
  decision: Decision;
  rule: Rule | undefined;
  active: boolean;
  reviewer: string;
  onSelect: () => void;
  onReviewed: (d: Decision) => void;
};

export default function DecisionCard({ decision: d, rule, active, reviewer, onSelect, onReviewed }: Props) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = tone(d);

  async function submit(action: "approve" | "override") {
    if (action === "override" && !reason.trim()) {
      setError("Add a reason before overriding.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onReviewed(await api.review(d.id, action, reviewer || "reviewer", reason));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      onClick={onSelect}
      className={`cursor-pointer rounded-lg border p-4 text-sm transition-colors ${
        active ? "border-neutral-900 dark:border-neutral-100" : "border-neutral-200 hover:border-neutral-400 dark:border-neutral-800"
      }`}
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[t].badge}`}>{proposal(d)}</span>
        <span className="text-xs text-neutral-500">{d.rule_title}</span>
        {d.clause_idx !== null && <span className="ml-auto text-xs text-neutral-500">clause {d.clause_idx + 1}</span>}
      </header>

      {d.quote && (
        <blockquote className="mt-3 border-l-2 border-neutral-300 pl-3 text-neutral-700 dark:border-neutral-700 dark:text-neutral-300">
          “{d.quote}”
        </blockquote>
      )}
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">{d.explanation}</p>

      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
        <div>
          <dt className="inline">Route: </dt>
          <dd className="inline">{d.route === "auto" ? "automatic" : "human review"}</dd>
        </div>
        <div>
          <dt className="inline">Why: </dt>
          <dd className="inline">{ROUTE_REASON[d.route_reason] ?? d.route_reason}</dd>
        </div>
        {d.confidence !== null && (
          <div>
            <dt className="inline">Confidence: </dt>
            <dd className="inline tabular-nums">{d.confidence.toFixed(2)}</dd>
          </div>
        )}
      </dl>

      {active && rule && (
        <details className="mt-3 text-xs text-neutral-500" onClick={(e) => e.stopPropagation()}>
          <summary className="cursor-pointer">
            {rule.id} definition ({rule.kind}, {rule.severity} severity)
          </summary>
          <p className="mt-1">{rule.definition}</p>
        </details>
      )}

      {d.status === "pending" && active && (
        <div className="mt-4 space-y-2" onClick={(e) => e.stopPropagation()}>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="Reason (required to override)"
            className="w-full rounded-md border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
          />
          <div className="flex gap-2">
            <button
              disabled={busy}
              onClick={() => submit("approve")}
              className="rounded-md bg-neutral-900 px-3 py-1.5 font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
            >
              Approve
            </button>
            <button
              disabled={busy}
              onClick={() => submit("override")}
              className="rounded-md border border-neutral-300 px-3 py-1.5 font-medium hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              Override
            </button>
          </div>
          {error && <p className="text-xs text-red-700 dark:text-red-300">{error}</p>}
        </div>
      )}

      {(d.status === "approved" || d.status === "overridden") && (
        <p className="mt-3 text-xs text-neutral-500">
          {d.status === "approved" ? "Approved" : "Overridden"} by {d.reviewer}
          {d.review_reason && `: “${d.review_reason}”`}
        </p>
      )}
    </article>
  );
}
