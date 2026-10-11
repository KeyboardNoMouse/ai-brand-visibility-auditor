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
    <main className="min-h-screen bg-slate-950">
      {/* Subtle background gradient */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-900 via-slate-950 to-indigo-950 opacity-80" />
      
      <div className="relative mx-auto max-w-4xl px-6 py-12 sm:py-16">
        {/* Header */}
        <header className="mb-12 space-y-4">
          <div className="inline-flex items-center gap-2 rounded-md bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-300 border border-indigo-500/20">
            <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
            AI Visibility Analysis
          </div>
          <h1 className="text-4xl font-bold text-white sm:text-5xl">
            Brand Visibility Auditor
          </h1>
          <p className="max-w-2xl text-lg text-slate-400">
            Analyze how AI models perceive and recommend your brand. Get actionable insights to improve visibility across AI-powered search and recommendations.
          </p>
        </header>

        {/* Form card */}
        <div className="mb-8 rounded-xl border border-slate-800 bg-slate-900/50 p-6 shadow-xl backdrop-blur-sm sm:p-8">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label htmlFor="brand" className="mb-2 block text-sm font-medium text-slate-300">
                  Brand Name
                </label>
                <input
                  id="brand"
                  type="text"
                  required
                  value={brandName}
                  onChange={(e) => setBrandName(e.target.value)}
                  placeholder="e.g. Stripe"
                  className="w-full rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2.5 text-white placeholder-slate-500 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
                />
              </div>
              <div>
                <label htmlFor="url" className="mb-2 block text-sm font-medium text-slate-300">
                  Website URL
                </label>
                <input
                  id="url"
                  type="url"
                  required
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://stripe.com"
                  className="w-full rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2.5 text-white placeholder-slate-500 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-lg transition hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  Running audit...
                </span>
              ) : (
                "Run Audit"
              )}
            </button>
          </form>
        </div>

        {/* Loading */}
        {loading && (
          <div className="rounded-lg border border-slate-800 bg-slate-900/30 p-6 text-center backdrop-blur-sm">
            <p className="text-sm text-slate-400">
              Analyzing page content, testing AI knowledge, and checking organic discovery. This takes 15-30 seconds.
            </p>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-4 backdrop-blur-sm">
            <div className="flex gap-3">
              <svg className="h-5 w-5 flex-shrink-0 text-red-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              <div className="text-sm text-red-200">
                <span className="font-semibold">Audit failed:</span> {error}
              </div>
            </div>
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <div className="space-y-6">
            <ResultsView result={result} />
          </div>
        )}

        <footer className="mt-16 border-t border-slate-800 pt-8 text-center text-sm text-slate-500">
          Powered by Gemini · Free tier optimized
        </footer>
      </div>
    </main>
  );
}
