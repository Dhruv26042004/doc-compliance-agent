"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import DecisionCard from "@/components/DecisionCard";
import type { Highlight } from "@/components/PdfViewer";
import { api, type Analysis, type Decision, type DocumentDetail, type Policy } from "@/lib/api";
import { RULE_STATUS_CLASSES, TONE_CLASSES, tone } from "@/lib/display";

// pdf.js needs the browser; never render it on the server.
const PdfViewer = dynamic(() => import("@/components/PdfViewer"), { ssr: false });

export default function DocumentPage() {
  return (
    <Suspense fallback={<p className="p-8 text-sm text-neutral-500">Loading…</p>}>
      <Review />
    </Suspense>
  );
}

function Review() {
  const { id } = useParams<{ id: string }>();
  const initialDecision = useSearchParams().get("decision");
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null | undefined>(undefined);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [activeId, setActiveId] = useState<string | null>(initialDecision);
  const [filter, setFilter] = useState<"review" | "all">("review");
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refreshAnalysis = useCallback(() => api.latestAnalysis(id).then(setAnalysis), [id]);

  useEffect(() => {
    Promise.all([api.document(id).then(setDoc), refreshAnalysis(), api.policy().then(setPolicy)]).catch((e) =>
      setError(e instanceof Error ? e.message : "Could not load the document"),
    );
    try {
      setReviewer(localStorage.getItem("reviewer") ?? "");
    } catch {}
  }, [id, refreshAnalysis]);

  const decisions = useMemo(() => {
    const all = analysis?.decisions ?? [];
    return filter === "review" ? all.filter((d) => d.route === "review") : all;
  }, [analysis, filter]);

  const highlights: Highlight[] = useMemo(
    () => decisions.filter((d) => d.rects.length).map((d) => ({ id: d.id, rects: d.rects, tone: tone(d) })),
    [decisions],
  );

  function onReviewed(updated: Decision) {
    setAnalysis((a) => a && { ...a, decisions: a.decisions.map((d) => (d.id === updated.id ? updated : d)) });
    refreshAnalysis(); // picks up the new per-rule status and counts
    const next = decisions.find((d) => d.status === "pending" && d.id !== updated.id);
    if (next) setActiveId(next.id);
  }

  function saveReviewer(name: string) {
    setReviewer(name);
    try {
      localStorage.setItem("reviewer", name);
    } catch {}
  }

  if (error) return <p className="p-8 text-sm text-red-700 dark:text-red-300">{error}</p>;
  if (!doc || analysis === undefined) return <p className="p-8 text-sm text-neutral-500">Loading…</p>;

  return (
    <main className="mx-auto grid max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_420px]">
      <section className="min-w-0">
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <h1 className="truncate text-lg font-semibold">{doc.filename}</h1>
          <Link href="/" className="shrink-0 text-sm text-neutral-500 hover:underline">
            All documents
          </Link>
        </div>
        {doc.has_layout ? (
          <PdfViewer
            url={api.fileUrl(doc.id)}
            pages={doc.pages}
            highlights={highlights}
            activeId={activeId}
            onSelect={setActiveId}
          />
        ) : (
          <TextView doc={doc} decisions={decisions} activeId={activeId} onSelect={setActiveId} />
        )}
      </section>

      <aside className="space-y-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
        {!analysis ? (
          <p className="rounded-lg border border-dashed border-neutral-300 p-4 text-sm text-neutral-500 dark:border-neutral-700">
            Not analyzed yet. Run the check from the documents page.
          </p>
        ) : (
          <>
            <Summary analysis={analysis} policy={policy} />
            <div className="flex items-center gap-2 text-sm">
              {(["review", "all"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`rounded-md px-3 py-1.5 ${filter === f ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900" : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800"}`}
                >
                  {f === "review" ? `Routed to review (${analysis.decisions.filter((d) => d.route === "review").length})` : `All decisions (${analysis.decisions.length})`}
                </button>
              ))}
            </div>
            <label className="block text-xs text-neutral-500">
              Reviewer name
              <input
                value={reviewer}
                onChange={(e) => saveReviewer(e.target.value)}
                placeholder="Your name"
                className="mt-1 w-full rounded-md border border-neutral-300 bg-transparent px-3 py-1.5 text-sm text-neutral-900 dark:border-neutral-700 dark:text-neutral-100"
              />
            </label>
            <div className="space-y-3">
              {decisions.map((d) => (
                <DecisionCard
                  key={d.id}
                  decision={d}
                  rule={policy?.rules.find((r) => r.id === d.rule_id)}
                  active={d.id === activeId}
                  reviewer={reviewer}
                  onSelect={() => setActiveId(d.id)}
                  onReviewed={onReviewed}
                />
              ))}
              {decisions.length === 0 && <p className="text-sm text-neutral-500">Nothing here.</p>}
            </div>
          </>
        )}
      </aside>
    </main>
  );
}

function Summary({ analysis, policy }: { analysis: Analysis; policy: Policy | null }) {
  return (
    <div className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium">{analysis.status === "complete" ? "Review complete" : `${analysis.n_pending} decisions to review`}</span>
        <span className="text-xs text-neutral-500">{analysis.n_auto} automatic</span>
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-1.5 text-xs">
        {Object.entries(analysis.rule_status).map(([ruleId, status]) => (
          <li key={ruleId} className="flex items-center justify-between gap-2" title={policy?.rules.find((r) => r.id === ruleId)?.title}>
            <span className="truncate text-neutral-600 dark:text-neutral-400">
              <span className="font-mono">{ruleId}</span> {policy?.rules.find((r) => r.id === ruleId)?.title}
            </span>
            <span className={`shrink-0 rounded-full px-2 py-0.5 ${RULE_STATUS_CLASSES[status]}`}>{status}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] leading-relaxed text-neutral-500">
        Policy {analysis.policy_id} v{analysis.policy_version} · pipeline {analysis.pipeline} · {analysis.model_version} · prompt{" "}
        {analysis.prompt_hash} · auto threshold {analysis.auto_threshold}
      </p>
    </div>
  );
}

/** Fallback for documents without page layout (DOCX parsed without LibreOffice). */
function TextView({
  doc,
  decisions,
  activeId,
  onSelect,
}: {
  doc: DocumentDetail;
  decisions: Decision[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="space-y-3 text-sm leading-relaxed">
      {doc.clauses.map((c) => {
        const hits = decisions.filter((d) => d.clause_id === c.id);
        const active = hits.find((d) => d.id === activeId);
        const t = hits[0] ? tone(active ?? hits[0]) : null;
        return (
          <p
            key={c.id}
            onClick={() => hits[0] && onSelect(hits[0].id)}
            className={`rounded-md p-2 ${t ? `${TONE_CLASSES[t].box} cursor-pointer` : ""} ${active ? "ring-2" : ""}`}
          >
            {c.text}
          </p>
        );
      })}
    </div>
  );
}
