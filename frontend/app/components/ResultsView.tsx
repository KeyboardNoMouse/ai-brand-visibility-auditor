"use client";

import { useState } from "react";
import type { AuditResult, PromptAggregate, Recommendation } from "../types";

// --- helpers --------------------------------------------------------------

function tone(score: number) {
  if (score >= 70) return { text: "text-emerald-400", bar: "bg-emerald-500", ring: "#10b981" };
  if (score >= 40) return { text: "text-amber-400", bar: "bg-amber-500", ring: "#f59e0b" };
  return { text: "text-rose-400", bar: "bg-rose-500", ring: "#f43f5e" };
}

function Card({
  title,
  children,
  right,
}: {
  title?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 shadow-lg backdrop-blur-sm">
      {title && (
        <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            {title}
          </h3>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

// --- composite ring -------------------------------------------------------

function ScoreRing({ score }: { score: number }) {
  const t = tone(score);
  const r = 52;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.min(100, Math.max(0, score)) / 100) * circ;
  return (
    <div className="relative h-36 w-36">
      <svg className="h-full w-full -rotate-90" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#1e293b" strokeWidth="8" />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          stroke={t.ring}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          className="transition-all duration-1000 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-4xl font-bold ${t.text}`}>
          {score.toFixed(0)}
        </span>
        <span className="text-xs text-slate-500">/ 100</span>
      </div>
    </div>
  );
}

// --- sub-score bar --------------------------------------------------------

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  const available = value !== null && value !== undefined;
  const v = available ? value : 0;
  const t = tone(v);
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-medium text-slate-300">{label}</span>
        <span className={`text-sm font-semibold ${available ? t.text : "text-slate-600"}`}>
          {available ? v.toFixed(0) : "N/A"}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
        {available && (
          <div
            className={`h-full rounded-full ${t.bar} transition-all duration-1000 ease-out`}
            style={{ width: `${Math.min(100, Math.max(0, v))}%` }}
          />
        )}
      </div>
    </div>
  );
}

// --- knowledge verdict pill ----------------------------------------------

const VERDICT_META: Record<string, { label: string; cls: string; desc: string }> = {
  known: {
    label: "Known",
    cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    desc: "The model genuinely recognizes this brand.",
  },
  hallucinated: {
    label: "Hallucinated",
    cls: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    desc: "The model invents inconsistent answers — it doesn't truly know the brand.",
  },
  unknown: {
    label: "Unknown",
    cls: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    desc: "The model has no reliable knowledge of this brand.",
  },
};

// --- bot access -----------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  training: "Training",
  search: "Search / Retrieval",
  user: "User-triggered",
  unknown: "Other",
};

function BotAccess({ botRules }: { botRules: Record<string, any> }) {
  const entries = Object.entries(botRules);
  if (entries.length === 0)
    return <p className="text-sm text-slate-500">No bot rules parsed.</p>;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {entries.map(([bot, info]: [string, any]) => (
        <div
          key={bot}
          className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-800/30 px-3 py-2.5"
        >
          <div className="min-w-0">
            <div className="truncate font-mono text-sm text-slate-200">{bot}</div>
            <div className="text-xs text-slate-500">
              {CATEGORY_LABELS[info.category] || info.category}
            </div>
          </div>
          <span
            className={`shrink-0 rounded-md px-2 py-1 text-xs font-medium ${
              info.allowed
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-rose-500/20 text-rose-300"
            }`}
          >
            {info.allowed ? "Allowed" : "Blocked"}
          </span>
        </div>
      ))}
    </div>
  );
}

// --- prompt card ----------------------------------------------------------

function PromptCard({ prompt }: { prompt: PromptAggregate }) {
  const [open, setOpen] = useState(false);
  const isKnowledge = prompt.prompt_type === "knowledge";
  const rate = prompt.mention_rate * 100;
  const t = tone(rate);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-800/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="mb-2 mr-2 inline-block rounded bg-slate-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-300">
            {prompt.prompt_type}
          </span>
          <span className="text-sm text-slate-300">{prompt.prompt_text}</span>
        </div>
        {!isKnowledge && (
          <span className={`shrink-0 text-sm font-bold ${t.text}`}>
            {prompt.mentions}/{prompt.runs}
          </span>
        )}
      </div>
      {prompt.runs_detail && prompt.runs_detail.length > 0 && (
        <>
          <button
            onClick={() => setOpen((o) => !o)}
            className="mt-3 text-xs font-medium text-slate-400 transition hover:text-slate-300"
          >
            {open ? "Hide responses" : "View responses"}
          </button>
          {open && (
            <div className="mt-3 space-y-2">
              {prompt.runs_detail.map((r) => (
                <div key={r.run_number} className="rounded-lg border border-slate-700 bg-slate-900/50 p-3 text-xs">
                  <div className="mb-2 flex justify-between text-slate-500">
                    <span>Run {r.run_number}</span>
                    {!isKnowledge && (
                      <span className={r.brand_mentioned ? "text-emerald-400 font-medium" : "text-slate-500"}>
                        {r.brand_mentioned ? "✓ mentioned" : "not mentioned"}
                      </span>
                    )}
                  </div>
                  <p className="whitespace-pre-wrap leading-relaxed text-slate-400">
                    {r.raw_response}
                  </p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// --- recommendations ------------------------------------------------------

// --- improvement plan (prominent, prioritized) ---------------------------

const SEV = {
  high: "bg-rose-500",
  medium: "bg-amber-500",
  low: "bg-slate-500",
} as const;

const SEV_LABEL = {
  high: "High impact",
  medium: "Medium impact",
  low: "Maintain",
} as const;

const SEV_ORDER = { high: 0, medium: 1, low: 2 } as const;

const CAT_LABEL: Record<string, string> = {
  mention: "AI knowledge & discovery",
  retrieval: "Search retrieval",
  access: "Crawler access",
  technical: "Technical readiness",
};

function ImprovementPlan({ recs }: { recs: Recommendation[] }) {
  // Sort by severity so the highest-impact actions come first.
  const sorted = [...recs].sort(
    (a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]
  );
  const actionable = sorted.filter((r) => r.severity !== "low");
  const maintaining = sorted.filter((r) => r.severity === "low");
  const counts = {
    high: recs.filter((r) => r.severity === "high").length,
    medium: recs.filter((r) => r.severity === "medium").length,
  };

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/50 shadow-lg backdrop-blur-sm overflow-hidden">
      <div className="border-b border-slate-800 bg-slate-900 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-white">
              Recommendations
            </h3>
            <p className="mt-1 text-sm text-slate-400">
              Prioritized actions to improve AI visibility
            </p>
          </div>
          <div className="hidden gap-2 sm:flex">
            {counts.high > 0 && (
              <span className="rounded-md bg-rose-500/20 px-2.5 py-1 text-xs font-semibold text-rose-300">
                {counts.high} high
              </span>
            )}
            {counts.medium > 0 && (
              <span className="rounded-md bg-amber-500/20 px-2.5 py-1 text-xs font-semibold text-amber-300">
                {counts.medium} medium
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="divide-y divide-slate-800">
        {actionable.length === 0 && (
          <div className="px-6 py-5 text-sm text-slate-400">
            No high-impact issues found — this brand is in good shape.
          </div>
        )}
        {actionable.map((r, i) => (
          <div key={r.id} className="flex gap-4 px-6 py-4">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-xs font-bold text-white">
              {i + 1}
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold ${
                  r.severity === "high"
                    ? "bg-rose-500/20 text-rose-300"
                    : "bg-amber-500/20 text-amber-300"
                }`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${SEV[r.severity]}`} />
                  {SEV_LABEL[r.severity]}
                </span>
                <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {CAT_LABEL[r.category] || r.category}
                </span>
              </div>
              <p className="text-sm leading-relaxed text-slate-300">{r.description}</p>
            </div>
          </div>
        ))}
      </div>

      {maintaining.length > 0 && (
        <details className="group border-t border-slate-800">
          <summary className="cursor-pointer list-none px-6 py-3 text-sm font-medium text-slate-400 transition hover:text-slate-300">
            <span className="group-open:hidden">
              Show {maintaining.length} maintenance note{maintaining.length > 1 ? "s" : ""}
            </span>
            <span className="hidden group-open:inline">Hide maintenance notes</span>
          </summary>
          <div className="divide-y divide-slate-800 bg-slate-900/30">
            {maintaining.map((r) => (
              <div key={r.id} className="flex gap-3 px-6 py-3">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-600" />
                <div>
                  <span className="mr-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                    {CAT_LABEL[r.category] || r.category}
                  </span>
                  <span className="text-sm leading-relaxed text-slate-400">{r.description}</span>
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

// --- main -----------------------------------------------------------------

export default function ResultsView({ result }: { result: AuditResult }) {
  const { audit, sub_scores, access, technical, mention, retrieval, recommendations } = result;
  const composite = audit.composite_score ?? 0;
  const verdict = mention?.brand_known ? VERDICT_META[mention.brand_known] : null;

  return (
    <div className="space-y-5">
      {/* Hero: score + verdict */}
      <div className="flex flex-col items-center gap-6 rounded-2xl border border-zinc-200 bg-white p-7 text-center shadow-sm sm:flex-row sm:text-left">
        <ScoreRing score={composite} />
        <div className="flex-1">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">
            AI Visibility Score
          </p>
          <p className="mt-1 text-lg font-semibold text-zinc-900">{audit.brand_name}</p>
          <p className="truncate text-sm text-zinc-400">{audit.url}</p>
          {verdict && (
            <div className="mt-3">
              <span className={`inline-block rounded-full border px-2.5 py-1 text-xs font-medium ${verdict.cls}`}>
                {verdict.label}
              </span>
              <p className="mt-2 text-sm leading-relaxed text-zinc-500">{verdict.desc}</p>
              {mention?.category && (
                <p className="mt-1 text-xs text-zinc-400">
                  Category: {mention.category}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Sub-scores */}
      <Card title="Signal Breakdown">
        <div className="grid gap-5 sm:grid-cols-2">
          <ScoreBar label="Crawler access" value={sub_scores.access} />
          <ScoreBar label="Technical readiness" value={sub_scores.technical} />
          <ScoreBar label="AI mention rate" value={sub_scores.mention} />
          <ScoreBar label="Retrieval visibility" value={sub_scores.retrieval} />
        </div>
      </Card>

      {/* Prominent improvement plan */}
      {recommendations.length > 0 && <ImprovementPlan recs={recommendations} />}

      {/* AI visibility */}
      {mention && mention.per_prompt.length > 0 && (
        <Card
          title="AI Visibility (Gemini)"
          right={
            <div className="flex gap-3 text-xs text-zinc-400">
              <span>Organic: <span className="font-medium text-zinc-600">{(mention.unbranded_mention_rate * 100).toFixed(0)}%</span></span>
            </div>
          }
        >
          <div className="space-y-2">
            {mention.per_prompt.map((p) => (
              <PromptCard key={p.prompt_text} prompt={p} />
            ))}
          </div>
        </Card>
      )}

      {/* Retrieval */}
      {retrieval && (
        <Card title="Search Retrieval (Exa.ai)">
          {retrieval.available ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {retrieval.brand_url_retrieved ? (
                  <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-600">
                    Retrieved · best rank {retrieval.best_rank}
                  </span>
                ) : (
                  <span className="rounded-full bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-600">
                    Not retrieved
                  </span>
                )}
                {typeof retrieval.retrieval_rate === "number" && (
                  <span className="text-xs text-zinc-400">
                    surfaced in {(retrieval.retrieval_rate * 100).toFixed(0)}% of{" "}
                    {retrieval.queries_run} queries
                  </span>
                )}
              </div>
              {retrieval.competitors && retrieval.competitors.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-zinc-400">
                    Competitors outranking this brand
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {retrieval.competitors.map((c) => (
                      <span
                        key={c.domain}
                        className="rounded-md border border-zinc-100 bg-zinc-50 px-2 py-1 text-xs text-zinc-600"
                      >
                        <span className="text-zinc-400">#{c.rank}</span> {c.domain}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-zinc-400">
              Not available: {retrieval.reason}
            </p>
          )}
        </Card>
      )}

      {/* Crawler access */}
      {access && (
        <Card title="AI Crawler Access">
          <BotAccess botRules={access.bot_rules} />
          <div className="mt-3 flex gap-4 text-xs text-zinc-400">
            <span>robots.txt: {access.robots_txt_found ? "found" : "not found"}</span>
            <span>llms.txt: {access.llms_txt_found ? "found" : "not found"}</span>
          </div>
        </Card>
      )}

      {/* Technical */}
      {technical && (
        <Card title="Technical Readiness">
          <div className="grid gap-x-6 gap-y-2 text-sm text-zinc-600 sm:grid-cols-2">
            <Row label="Meta description" ok={!!technical.meta_description} />
            <Row label="Schema.org data" ok={technical.has_schema_data} note={technical.schema_types.join(", ")} />
            <Row label="Single H1" ok={technical.h1_count === 1} note={`${technical.h1_count} found`} />
            <Row label="Statistics" ok={technical.has_statistics} />
            <Row label="Quotations" ok={technical.has_quotations} />
            <Row label="Outbound citations" ok={technical.has_outbound_citations} />
            <Row label="Word count" ok={technical.word_count >= 300} note={`${technical.word_count} words`} />
          </div>
        </Card>
      )}
    </div>
  );
}

function Row({ label, ok, note }: { label: string; ok: boolean; note?: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] ${
          ok ? "bg-emerald-100 text-emerald-600" : "bg-zinc-100 text-zinc-400"
        }`}
      >
        {ok ? "✓" : "–"}
      </span>
      <span className="text-zinc-600">{label}</span>
      {note && <span className="ml-auto text-xs text-zinc-400">{note}</span>}
    </div>
  );
}
