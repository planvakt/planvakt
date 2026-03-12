"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { ExternalLink } from "lucide-react";

type Lead = {
  id: string;
  title: string | null;
  kommune: string | null;
  gnr: string | null;
  bnr: string | null;
  adresse: string | null;
  ai_summary: string | null;
  ai_score: number | null;
  url: string | null;
};

function getScoreBadge(score: number | null): { className: string; label: string } {
  if (score == null) return { className: "bg-slate-100 text-slate-800 border-slate-200 border", label: "—" };
  if (score >= 90) return { className: "bg-green-100 text-green-800 border-green-200 border", label: "Super Match" };
  if (score >= 70) return { className: "bg-blue-100 text-blue-800 border-blue-200 border", label: "God Match" };
  return { className: "bg-yellow-100 text-yellow-800 border-yellow-200 border", label: "Mulighet" };
}

function formatLocation(lead: Lead): string {
  const addr = lead.adresse?.trim();
  if (addr) return addr;
  const gnr = lead.gnr?.trim();
  const bnr = lead.bnr?.trim();
  const kom = lead.kommune?.trim();
  if (gnr || bnr) {
    const part = [gnr && `Gnr ${gnr}`, bnr && `Bnr ${bnr}`].filter(Boolean).join(", ");
    return kom ? `${part}, ${kom}` : part;
  }
  return kom || "—";
}

export default function DashboardPage() {
  const router = useRouter();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [subscriptionStatus, setSubscriptionStatus] = useState<"active" | "free" | null>(null);

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
        const { data: profile, error: profileError } = await supabase
          .from("profiles")
          .select("subscription_status")
          .eq("id", session.user.id)
          .maybeSingle();

        if (profileError) {
          console.warn("Profile fetch warning:", profileError.message);
        }
        const status = profile?.subscription_status;
        setSubscriptionStatus(status === "active" ? "active" : "free");

        const { data, error: leadsError } = await supabase
          .from("leads")
          .select("id, title, kommune, gnr, bnr, adresse, ai_summary, ai_score, url")
          .eq("is_gold", true)
          .order("ai_score", { ascending: false });

        if (leadsError) throw leadsError;
        setLeads((data as Lead[]) ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Kunne ikke laste saker");
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
        <p className="text-slate-400">Laster saker...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-2">Feil: {error}</p>
          <p className="text-slate-500 text-sm">Sjekk at du er logget inn og at tabellene finnes.</p>
        </div>
      </div>
    );
  }

  const isPremium = subscriptionStatus === "active";

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <div className="max-w-4xl mx-auto px-4 py-10">
        <h1 className="text-3xl font-bold text-white mb-8 tracking-tight">
          TeigVis Dashboard
        </h1>

        {leads.length === 0 ? (
          <p className="text-slate-400">Ingen gull-saker funnet. Vi viser kun saker som er vurdert som relevante (is_gold = true).</p>
        ) : (
          <ul className="space-y-6">
            {leads.map((lead) => {
              const score = lead.ai_score ?? 0;
              const badge = getScoreBadge(lead.ai_score);

              return (
                <li
                  key={lead.id}
                  className="bg-slate-800 rounded-xl border border-slate-700/50 shadow-lg overflow-hidden"
                >
                  <div className="p-6 relative">
                    {/* Score badge – top right */}
                    <div
                      className={`absolute top-5 right-5 px-3 py-1.5 rounded-lg text-sm font-semibold border ${badge.className}`}
                    >
                      {score} · {badge.label}
                    </div>

                    {/* Header: Lead title */}
                    <h2 className="text-xl font-bold text-white pr-24 mb-4">
                      {lead.title ?? "Ukjent tittel"}
                    </h2>

                    {/* Teaser: AI score + summary – always visible */}
                    <div className="mb-4 rounded-lg bg-indigo-500/20 border border-indigo-400/40 p-4">
                      <p className="text-xs font-semibold text-indigo-300 uppercase tracking-wider mb-2">
                        AI vurdering (score {score}/100)
                      </p>
                      <p className="text-slate-200 text-sm leading-relaxed">
                        {lead.ai_summary ?? "Ingen sammendrag."}
                      </p>
                    </div>

                    {/* Location block: full for premium, blurred + CTA for free */}
                    <div className="mb-5">
                      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                        Lokasjon
                      </p>
                      {isPremium ? (
                        <p className="text-slate-300 text-sm">
                          {formatLocation(lead)}
                        </p>
                      ) : (
                        <div className="relative rounded-lg bg-slate-700/50 border border-slate-600/50 p-4 min-h-[3rem] flex items-center justify-center">
                          <p className="text-slate-400 text-sm blur-md select-none pointer-events-none">
                            {formatLocation(lead) || "Adresse skjult"}
                          </p>
                          <a
                            href="https://buy.stripe.com/test_aFaaEX0yb1Wr8NzgAH6Ri00"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="absolute inset-0 flex items-center justify-center rounded-lg"
                          >
                            <span className="inline-flex items-center justify-center px-6 py-3 border border-transparent text-base font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 shadow-sm shadow-indigo-200 transition-all duration-200">
                              Oppgrader til Pro for å se detaljer 🔓
                            </span>
                          </a>
                        </div>
                      )}
                    </div>

                    {/* Link to original PDF – only for premium */}
                    {isPremium && lead.url && (
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
