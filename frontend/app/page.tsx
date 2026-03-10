"use client";

import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";
import { Sparkles, ExternalLink } from "lucide-react";

type Lead = {
  id: string;
  title: string | null;
  url: string | null;
  ai_summary: string | null;
  ai_category: string | null;
  ai_score: number | null;
  gnr_bnr: string | null;
  municipality_id: string | null;
};

type Match = {
  id: string;
  match_score: number | null;
  match_reason: string | null;
  lead_id: string;
  leads: Lead | Lead[] | null;
};

function getScoreBadgeStyle(score: number | null): string {
  if (score == null) return "bg-slate-500 text-white";
  if (score >= 90) return "bg-emerald-600 text-white";
  if (score >= 70) return "bg-blue-600 text-white";
  if (score >= 40) return "bg-amber-500 text-slate-900";
  return "bg-slate-500 text-white";
}

export default function DashboardPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const supabase = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
    );

    async function fetchMatches() {
      try {
        const { data, error: fetchError } = await supabase
          .from("matches")
          .select("*, leads(*)")
          .order("match_score", { ascending: false });

        if (fetchError) throw fetchError;
        setMatches((data as Match[]) ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load matches");
      } finally {
        setLoading(false);
      }
    }

    fetchMatches();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <p className="text-slate-400">Laster matcher...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <p className="text-red-400">Feil: {error}</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <div className="max-w-4xl mx-auto px-4 py-10">
        <h1 className="text-3xl font-bold text-white mb-8 tracking-tight">
          TeigVis Dashboard
        </h1>

        {matches.length === 0 ? (
          <p className="text-slate-400">Ingen matcher funnet.</p>
        ) : (
          <ul className="space-y-6">
            {matches.map((match) => {
              const lead = Array.isArray(match.leads) ? match.leads[0] : match.leads;
              const score = match.match_score ?? 0;

              return (
                <li
                  key={match.id}
                  className="bg-slate-800 rounded-xl border border-slate-700/50 shadow-lg overflow-hidden"
                >
                  <div className="p-6 relative">
                    {/* Score badge – top right */}
                    <div
                      className={`absolute top-5 right-5 px-3 py-1 rounded-full text-sm font-semibold ${getScoreBadgeStyle(match.match_score)}`}
                    >
                      {score}
                    </div>

                    {/* Header: Lead title */}
                    <h2 className="text-xl font-bold text-white pr-24 mb-4">
                      {lead?.title ?? "Ukjent tittel"}
                    </h2>

                    {/* TeigVis Analyse – highlighted box */}
                    <div className="mb-4 rounded-lg bg-indigo-500/15 border border-indigo-400/30 p-4">
                      <p className="text-sm font-medium text-indigo-200 flex items-center gap-2 mb-2">
                        <Sparkles className="h-4 w-4 shrink-0" />
                        TeigVis Analyse
                      </p>
                      <p className="text-slate-200 text-sm leading-relaxed">
                        {match.match_reason ?? "—"}
                      </p>
                    </div>

                    {/* Details: AI summary */}
                    <p className="text-slate-400 text-sm leading-relaxed mb-5">
                      {lead?.ai_summary ?? "Ingen sammendrag."}
                    </p>

                    {/* Action: link to original document */}
                    {lead?.url && (
                      <a
                        href={lead.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-100 font-medium text-sm transition-colors"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Les originaldokument
                      </a>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
