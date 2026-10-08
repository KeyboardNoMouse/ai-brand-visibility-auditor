"use client";

import { useState } from "react";
import { runAudit } from "./api";
import type { AuditResult } from "./types";
import ResultsView from "./components/ResultsView";

export default function Home() {
  const [brandName, setBrandName] = useState("");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AuditResult | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const data = await runAudit(brandName.trim(), url.trim());
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-16 sm:py-20">
      {/* Header */}
      <header className="mb-10 text-center">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1 text-xs font-medium text-zinc-500">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Generative Engine Optimization
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 sm:text-4xl">
          AI Visibility Auditor
        </h1>
        <p className="mx-auto mt-3 max-w-lg text-[15px] leading-relaxed text-zinc-500">
          Measure how visible a brand truly is to AI models like Gemini — and
          whether it&apos;s recognized, hallucinated, or unknown.
        </p>
      </header>

      {/* Form card */}
      <form
        onSubmit={handleSubmit}
        className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-7"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="brand" className="mb-1.5 block text-sm font-medium text-zinc-700">
              Brand name
            </label>
            <input
              id="brand"
              type="text"
              required
              value={brandName}
              onChange={(e) => setBrandName(e.target.value)}
              placeholder="e.g. Stripe"
              className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3.5 py-2.5 text-[15px] text-zinc-900 placeholder-zinc-400 outline-none transition focus:border-zinc-900 focus:bg-white focus:ring-4 focus:ring-zinc-900/5"
            />
          </div>
          <div>
            <label htmlFor="url" className="mb-1.5 block text-sm font-medium text-zinc-700">
              Website URL
            </label>
            <input
              id="url"
              type="url"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://stripe.com"
              className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3.5 py-2.5 text-[15px] text-zinc-900 placeholder-zinc-400 outline-none transition focus:border-zinc-900 focus:bg-white focus:ring-4 focus:ring-zinc-900/5"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={loading}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-zinc-900 px-4 py-2.5 text-[15px] font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Auditing… (15–30s)
            </>
          ) : (
            "Run audit"
          )}
        </button>
      </form>

      {/* Loading skeleton */}
      {loading && (
        <div className="mt-6 rounded-2xl border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500 animate-in">
          Scraping the page, probing the model&apos;s knowledge, and testing
          organic discovery. This takes 15–30 seconds.
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 animate-in">
          <span className="font-medium">Couldn&apos;t complete the audit.</span>{" "}
          {error}
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="mt-8 animate-in">
          <ResultsView result={result} />
        </div>
      )}

      <footer className="mt-16 text-center text-xs text-zinc-400">
        Powered by Gemini · single-page local tool
      </footer>
    </main>
  );
}
