import type { Decision, RuleStatus } from "./api";

/** What the model proposed, in words a reviewer can approve or reject. */
export function proposal(d: Decision): string {
  switch (d.kind) {
    case "finding":
      return d.verdict === "violation"
        ? `Violates ${d.rule_id}`
        : d.verdict === "satisfies"
          ? `Satisfies ${d.rule_id}`
          : `Flag for ${d.rule_id}`;
    case "rejected_finding":
      return `Does not match ${d.rule_id} (verifier overruled)`;
    case "possible_miss":
      return `Does not match ${d.rule_id} (possible miss)`;
    case "missing_required":
      return `Document has no ${d.rule_id} clause`;
  }
}

export const ROUTE_REASON: Record<string, string> = {
  high_confidence: "High confidence, verified quote",
  low_confidence: "Below the confidence threshold",
  verifier_llm: "Verifier disagreed with the classifier",
  verifier_quote_not_found: "Quoted text is not in the clause",
  small_model_disagrees: "Small model flags a possible miss",
  required_rule_missing: "Required clause not found",
};

/** Highlight color for a decision: red violation, amber flag, green satisfies, blue needs a human. */
export function tone(d: Decision): "red" | "amber" | "green" | "blue" | "gray" {
  if (d.status === "pending") return "blue";
  const applies = d.final_applies ?? d.proposed_applies;
  if (d.kind === "missing_required") return applies ? "green" : "red";
  if (!applies) return "gray";
  return d.verdict === "violation" ? "red" : d.verdict === "satisfies" ? "green" : "amber";
}

export const TONE_CLASSES = {
  red: { badge: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200", box: "bg-red-500/25 ring-red-600" },
  amber: { badge: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200", box: "bg-amber-400/30 ring-amber-600" },
  green: { badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200", box: "bg-emerald-400/25 ring-emerald-600" },
  blue: { badge: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200", box: "bg-sky-400/25 ring-sky-600" },
  gray: { badge: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300", box: "bg-neutral-400/20 ring-neutral-500" },
} as const;

export const RULE_STATUS_CLASSES: Record<RuleStatus, string> = {
  violated: TONE_CLASSES.red.badge,
  flagged: TONE_CLASSES.amber.badge,
  satisfied: TONE_CLASSES.green.badge,
  clear: TONE_CLASSES.gray.badge,
  pending: TONE_CLASSES.blue.badge,
};

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
