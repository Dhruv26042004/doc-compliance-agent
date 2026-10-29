"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { metricsApi, type EvalRun, type Metrics } from "@/lib/api";

// Validated categorical slots 1-3 (light / dark steps) and chart chrome.
const PALETTE = {
  light: { s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", grid: "#e1e0d9", axis: "#c3c2b7", muted: "#898781", ink: "#0b0b0b", surface: "#fcfcfb" },
  dark: { s1: "#3987e5", s2: "#d95926", s3: "#199e70", grid: "#2c2c2a", axis: "#383835", muted: "#898781", ink: "#f0efec", surface: "#1a1a19" },
};

function usePalette() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(mq.matches);
    const on = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return PALETTE[dark ? "dark" : "light"];
}

const pct = (x: number | null | undefined, digits = 0) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(digits)}%`);

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [evals, setEvals] = useState<EvalRun[] | null>(null);
  const [split, setSplit] = useState("test_core");
  const [error, setError] = useState<string | null>(null);
  const c = usePalette();

  useEffect(() => {
    Promise.all([metricsApi.metrics().then(setMetrics), metricsApi.evals().then(setEvals)]).catch((e) =>
      setError(e instanceof Error ? e.message : "Could not load metrics"),
    );
  }, []);

  const splits = useMemo(() => [...new Set(evals?.map((r) => r.split))].sort(), [evals]);
  const runs = useMemo(
    () =>
      (evals ?? [])
        .filter((r) => r.split === split)
        .map((r, i) => ({
          ...r,
          label: `#${i + 1}`,
          name: `${r.pipeline} · policy v${r.policy_version}`,
          when: new Date(r.run_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
        })),
    [evals, split],
  );
  const overrideRows = useMemo(
    () => (metrics?.rules ?? []).filter((r) => r.reviewed > 0).map((r) => ({ ...r, rate: r.override_rate ?? 0 })),
    [metrics],
  );

  if (error) return <p className="p-8 text-sm text-red-700 dark:text-red-300">{error}</p>;
  if (!metrics || !evals) return <p className="p-8 text-sm text-neutral-500">Loading…</p>;

  const axis = { stroke: c.axis, tick: { fill: c.muted, fontSize: 12 }, tickLine: false };
  const tooltipStyle = {
    contentStyle: { background: c.surface, border: `1px solid ${c.grid}`, borderRadius: 6, fontSize: 12, color: c.ink },
    labelStyle: { color: c.ink, fontWeight: 600 },
  };

  return (
    <main className="mx-auto max-w-7xl space-y-10 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Live numbers from analyses and reviews, and offline precision/recall from every evaluation run.
        </p>
      </div>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Tile label="Decisions made automatically" value={pct(metrics.automation_rate)} note={`${metrics.auto_decisions} of ${metrics.decisions}`} />
        <Tile label="Clauses needing no human" value={pct(metrics.clauses_without_human)} note={`${metrics.clauses_analyzed} clauses analyzed`} />
        <Tile label="Reviewer override rate" value={pct(metrics.override_rate)} note={`${metrics.reviewed} reviewed`} />
        <Tile label="Awaiting review" value={String(metrics.pending_reviews)} note={`${metrics.documents} documents`} />
        <Tile label="Labels collected" value={String(metrics.labels)} note="from reviews" />
      </section>

      <section>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-medium">Precision and recall across evaluation runs</h2>
            <p className="text-sm text-neutral-500">Micro-averaged over all rules. Each point is one saved run, in order.</p>
          </div>
          <select
            value={split}
            onChange={(e) => setSplit(e.target.value)}
            className="rounded-md border border-neutral-300 bg-transparent px-3 py-1.5 text-sm dark:border-neutral-700"
          >
            {splits.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="mt-4 h-72 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
          <ResponsiveContainer>
            <LineChart data={runs} margin={{ top: 12, right: 40, bottom: 4, left: 0 }}>
              <CartesianGrid vertical={false} stroke={c.grid} />
              <XAxis dataKey="label" {...axis} />
              <YAxis domain={[0, 1]} tickFormatter={(v) => pct(v)} {...axis} axisLine={false} width={44} />
              <Tooltip
                {...tooltipStyle}
                labelFormatter={(_, p) => (p?.[0] ? `${p[0].payload.name} — ${p[0].payload.when}` : "")}
                formatter={(v, name) => [pct(Number(v), 1), name]}
              />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: c.muted }} />
              <Line type="linear" dataKey="precision" name="Precision" stroke={c.s1} strokeWidth={2} dot={{ r: 4, fill: c.s1, stroke: c.surface, strokeWidth: 2 }} activeDot={{ r: 6 }}>
                <LabelList dataKey="precision" position="top" formatter={(v: unknown) => pct(Number(v))} style={{ fill: c.muted, fontSize: 11 }} />
              </Line>
              <Line type="linear" dataKey="recall" name="Recall" stroke={c.s2} strokeWidth={2} dot={{ r: 4, fill: c.s2, stroke: c.surface, strokeWidth: 2 }} activeDot={{ r: 6 }}>
                <LabelList dataKey="recall" position="bottom" formatter={(v: unknown) => pct(Number(v))} style={{ fill: c.muted, fontSize: 11 }} />
              </Line>
            </LineChart>
          </ResponsiveContainer>
        </div>
        <ol className="mt-3 grid gap-x-6 gap-y-1 text-xs text-neutral-500 sm:grid-cols-2">
          {runs.map((r) => (
            <li key={r.file}>
              <span className="font-mono">{r.label}</span> {r.name} · {r.model_version} · {r.when}
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-8 lg:grid-cols-2">
        <div>
          <h2 className="font-medium">Override rate by rule</h2>
          <p className="text-sm text-neutral-500">Share of reviewed decisions where the reviewer disagreed with the model.</p>
          <div className="mt-4 h-72 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            {overrideRows.length === 0 ? (
              <p className="p-6 text-sm text-neutral-500">No reviews yet.</p>
            ) : (
              <ResponsiveContainer>
                <BarChart data={overrideRows} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 4 }}>
                  <CartesianGrid horizontal={false} stroke={c.grid} />
                  <XAxis type="number" domain={[0, 1]} tickFormatter={(v) => pct(v)} {...axis} />
                  <YAxis type="category" dataKey="rule_id" {...axis} axisLine={false} width={44} />
                  <Tooltip
                    {...tooltipStyle}
                    cursor={{ fill: c.grid, opacity: 0.4 }}
                    labelFormatter={(_, p) => (p?.[0] ? `${p[0].payload.rule_id} ${p[0].payload.title}` : "")}
                    formatter={(v, _n, p) => [`${pct(Number(v))} (${p.payload.overridden} of ${p.payload.reviewed})`, "Overridden"]}
                  />
                  <Bar dataKey="rate" name="Override rate" fill={c.s1} radius={[0, 4, 4, 0]} barSize={14}>
                    <LabelList dataKey="rate" position="right" formatter={(v: unknown) => pct(Number(v))} style={{ fill: c.muted, fontSize: 11 }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div>
          <h2 className="font-medium">Daily volume</h2>
          <p className="text-sm text-neutral-500">From the audit log.</p>
          <div className="mt-4 h-72 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <ResponsiveContainer>
              <BarChart data={metrics.volume} margin={{ top: 16, right: 8, bottom: 4, left: 0 }} barGap={2}>
                <CartesianGrid vertical={false} stroke={c.grid} />
                <XAxis dataKey="day" {...axis} />
                <YAxis allowDecimals={false} {...axis} axisLine={false} width={36} />
                <Tooltip {...tooltipStyle} cursor={{ fill: c.grid, opacity: 0.4 }} />
                <Legend wrapperStyle={{ fontSize: 12, color: c.muted }} />
                {(
                  [
                    ["uploaded", "Uploaded", c.s1],
                    ["analyzed", "Analyzed", c.s2],
                    ["reviewed", "Reviews", c.s3],
                  ] as const
                ).map(([key, name, color]) => (
                  <Bar key={key} dataKey={key} name={name} fill={color} radius={[4, 4, 0, 0]} maxBarSize={28}>
                    <LabelList dataKey={key} position="top" style={{ fill: c.muted, fontSize: 11 }} />
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      <section>
        <h2 className="font-medium">Per-rule review statistics</h2>
        <div className="mt-4 overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-900">
              <tr>
                <th className="px-4 py-2 font-medium">Rule</th>
                <th className="px-4 py-2 text-right font-medium">Decisions</th>
                <th className="px-4 py-2 text-right font-medium">Automatic</th>
                <th className="px-4 py-2 text-right font-medium">Pending</th>
                <th className="px-4 py-2 text-right font-medium">Reviewed</th>
                <th className="px-4 py-2 text-right font-medium">Override rate</th>
                <th className="px-4 py-2 text-right font-medium">Precision (reviewer-measured)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 tabular-nums dark:divide-neutral-800">
              {metrics.rules.map((r) => (
                <tr key={r.rule_id}>
                  <td className="px-4 py-2">
                    <span className="font-mono text-xs text-neutral-500">{r.rule_id}</span> {r.title}
                  </td>
                  <td className="px-4 py-2 text-right">{r.decisions}</td>
                  <td className="px-4 py-2 text-right">{r.auto}</td>
                  <td className="px-4 py-2 text-right">{r.pending}</td>
                  <td className="px-4 py-2 text-right">{r.reviewed}</td>
                  <td className="px-4 py-2 text-right">{pct(r.override_rate)}</td>
                  <td className="px-4 py-2 text-right">{pct(r.reviewer_precision)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
      <p className="text-xs text-neutral-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      <p className="mt-0.5 text-xs text-neutral-500">{note}</p>
    </div>
  );
}
