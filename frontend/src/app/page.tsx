"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Analysis, type DocumentSummary } from "@/lib/api";
import { formatDate } from "@/lib/display";

type Row = { doc: DocumentSummary; analysis: Analysis | null };

export default function DocumentsPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, string>>({});
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const docs = await api.documents();
      const analyses = await Promise.all(docs.map((d) => api.latestAnalysis(d.id)));
      setRows(docs.map((doc, i) => ({ doc, analysis: analyses[i] })));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the API");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function upload(file: File) {
    setBusy((b) => ({ ...b, upload: `Uploading ${file.name}…` }));
    try {
      await api.upload(file);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy((b) => without(b, "upload"));
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function analyze(id: string) {
    setBusy((b) => ({ ...b, [id]: "Analyzing… about a minute" }));
    try {
      await api.analyze(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setBusy((b) => without(b, id));
    }
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Documents</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Upload a contract (PDF or DOCX), run the policy check, then review what the system was unsure about.
          </p>
        </div>
        <label className="cursor-pointer rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300">
          {busy.upload ?? "Upload contract"}
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.docx"
            className="hidden"
            disabled={!!busy.upload}
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
        </label>
      </div>

      {error && (
        <p className="mt-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{error}</p>
      )}

      <div className="mt-8 overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-900">
            <tr>
              <th className="px-4 py-3 font-medium">Document</th>
              <th className="px-4 py-3 font-medium">Pages</th>
              <th className="px-4 py-3 font-medium">Clauses</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Uploaded</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {rows === null && !error && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-neutral-500">
                  Loading…
                </td>
              </tr>
            )}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-neutral-500">
                  No documents yet. Upload a contract to start.
                </td>
              </tr>
            )}
            {rows?.map(({ doc, analysis }) => (
              <tr key={doc.id}>
                <td className="px-4 py-3">
                  <Link href={`/documents/${doc.id}`} className="font-medium hover:underline">
                    {doc.filename}
                  </Link>
                </td>
                <td className="px-4 py-3 tabular-nums">{doc.n_pages || "–"}</td>
                <td className="px-4 py-3 tabular-nums">{doc.n_clauses}</td>
                <td className="px-4 py-3">
                  <StatusBadge analysis={analysis} />
                </td>
                <td className="px-4 py-3 text-neutral-500">{formatDate(doc.created_at)}</td>
                <td className="px-4 py-3 text-right">
                  {busy[doc.id] ? (
                    <span className="text-neutral-500">{busy[doc.id]}</span>
                  ) : (
                    <button
                      onClick={() => analyze(doc.id)}
                      className="rounded-md border border-neutral-300 px-3 py-1.5 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
                    >
                      {analysis ? "Re-analyze" : "Analyze"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

function StatusBadge({ analysis }: { analysis: Analysis | null }) {
  if (!analysis) return <span className="text-neutral-500">Not analyzed</span>;
  if (analysis.status === "needs_review")
    return (
      <span className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-medium text-sky-800 dark:bg-sky-950 dark:text-sky-200">
        {analysis.n_pending} to review
      </span>
    );
  return (
    <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
      Complete
    </span>
  );
}

function without(obj: Record<string, string>, key: string): Record<string, string> {
  const copy = { ...obj };
  delete copy[key];
  return copy;
}
