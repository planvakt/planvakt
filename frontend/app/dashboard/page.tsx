"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { ExternalLink } from "lucide-react";

type Lead = {
  title: string | null;
  ai_summary: string | null;
  url: string | null;
  gnr_bnr: string | null;
};

type Match = {
  id: string;
  match_score: number | null;
  match_reason: string | null;
  leads: Lead | Lead[] | null;
};

function getScoreBadge(score: number | null): { className: string; label: string } {
  if (score == null) return { className: "bg-slate-100 text-slate-800 border-slate-200 border", label: "—" };
  if (score >= 90) return { className: "bg-green-100 text-green-800 border-green-200 border", label: "Super Match" };
  if (score >= 70) return { className: "bg-blue-100 text-blue-800 border-blue-200 border", label: "God Match" };
  return { className: "bg-yellow-100 text-yellow-800 border-yellow-200 border", label: "Mulighet" };
}

export default function DashboardPage() {
  const router = useRouter();
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    const supabase = createClient();

    async function init() {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) {
        router.replace("/login");
        return;
      }
      setAuthChecked(true);

      try {
        const { data, error: fetchError } = await supabase
          .from("matches")
          .select("id, match_score, match_reason, leads(title, ai_summary, url, gnr_bnr)")
          .order("match_score", { ascending: false });

        if (fetchError) throw fetchError;
        setMatches((data as Match[]) ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Kunne ikke laste matcher");
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [router]);

  if (!authChecked && !error) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <p className="text-slate-400">Sjekker innlogging...</p>
      </div>
    );
  }

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
                    {(() => {
                      const badge = getScoreBadge(match.match_score);
                      return (
                        <div
                          className={`absolute top-5 right-5 px-3 py-1.5 rounded-lg text-sm font-semibold border ${badge.className}`}
                        >
                          {score} · {badge.label}
                        </div>
                      );
                    })()}

                    {/* Header: Lead title */}
                    <h2 className="text-xl font-bold text-white pr-24 mb-4">
                      {lead?.title ?? "Ukjent tittel"}
                    </h2>

                    {/* AI elevator pitch – clearly highlighted */}
                    <div className="mb-4 rounded-lg bg-indigo-500/20 border border-indigo-400/40 p-4">
                      <p className="text-xs font-semibold text-indigo-300 uppercase tracking-wider mb-2">
                        AI vurdering
                      </p>
                      <p className="text-slate-200 text-sm leading-relaxed">
                        {match.match_reason ?? "—"}
                      </p>
                    </div>

                    {/* Details: AI summary */}
                    <p className="text-slate-400 text-sm leading-relaxed mb-5">
                      {lead?.ai_summary ?? "Ingen sammendrag."}
                    </p>

                    {/* Action: link to original PDF */}
                    {lead?.url && (
                      <a
                        href={lead.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-100 font-medium text-sm transition-colors"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Les original PDF
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
