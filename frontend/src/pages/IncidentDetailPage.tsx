import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, Link } from "@tanstack/react-router";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { api } from "@/services/api";
import { GlassCard } from "@/components/shared/GlassCard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { SeverityBadge } from "@/components/shared/SeverityBadge";

export default function IncidentDetailPage() {
  const { id } = useParams({ strict: false }) as { id: string };

  const { data: incident, isLoading, isError } = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api.getIncident(Number(id)),
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-full min-h-[50vh]">
        <LoadingSpinner />
      </div>
    );
  }

  if (isError || !incident) {
    return (
      <div className="p-6 text-center text-[#ffb4ab]">
        <GlassCard className="border-l-4 border-l-[#ffb4ab] inline-block p-6">
          <h2 className="text-xl font-bold mb-2">Data Retrieval Failed</h2>
          <p className="text-[#bbc9ce]">Could not access incident record SG-{id}.</p>
        </GlassCard>
      </div>
    );
  }

  // Parse SHAP values if present
  let shapValues = [];
  try {
    if (typeof incident.shap_values === "string") {
      shapValues = JSON.parse(incident.shap_values);
    } else if (Array.isArray(incident.shap_values)) {
      shapValues = incident.shap_values;
    }
  } catch (e) {
    console.error("Failed to parse SHAP values:", e);
  }

  return (
    <div className="p-6 max-w-6xl mx-auto font-sans text-[#dde4e6] space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to="/incidents"
            className="text-[#00d9ff] hover:text-[#afecff] flex items-center gap-1 transition-colors bg-[#080f11] p-2 rounded border border-[rgba(255,255,255,0.08)] hover:bg-[#00d9ff]/10"
          >
            <span className="material-symbols-outlined">arrow_back</span>
          </Link>
          <h1 className="text-3xl font-bold tracking-tight">
            Incident Report <span className="text-[#00d9ff]">#SG-{id}</span>
          </h1>
        </div>
        <SeverityBadge severity={incident.severity || "unknown"} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Core Info */}
        <div className="md:col-span-1 space-y-6">
          <GlassCard className="p-6">
            <h2 className="text-lg font-bold text-[#bbc9ce] mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined">info</span>
              Details
            </h2>
            <div className="space-y-4">
              <div>
                <p className="text-[#859398] text-sm uppercase tracking-wider mb-1">Time</p>
                <p className="font-mono">{incident.timestamp ? new Date(incident.timestamp).toLocaleString() : "Unknown"}</p>
              </div>
              <div>
                <p className="text-[#859398] text-sm uppercase tracking-wider mb-1">Attack Type</p>
                <p className="text-[#ffdeaa] font-medium">{incident.attack_type || "Unknown"}</p>
              </div>
              <div>
                <p className="text-[#859398] text-sm uppercase tracking-wider mb-1">Threat Level</p>
                <p>{incident.threat_level || "N/A"}</p>
              </div>
              <div>
                <p className="text-[#859398] text-sm uppercase tracking-wider mb-1">Status</p>
                <p className="capitalize">{incident.status || "Open"}</p>
              </div>
            </div>
          </GlassCard>
        </div>

        {/* AI Explainability */}
        <div className="md:col-span-2 space-y-6">
          <GlassCard className="p-6">
            <h2 className="text-lg font-bold text-[#bbc9ce] mb-6 flex items-center gap-2">
              <span className="material-symbols-outlined">psychology</span>
              AI Explainability (SHAP Values)
            </h2>
            
            {shapValues && shapValues.length > 0 ? (
              <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={shapValues}
                    layout="vertical"
                    margin={{ top: 5, right: 30, left: 40, bottom: 5 }}
                  >
                    <XAxis type="number" hide />
                    <YAxis 
                      dataKey="feature" 
                      type="category" 
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "#bbc9ce", fontSize: 12 }}
                      width={100}
                    />
                    <Tooltip 
                      contentStyle={{ 
                        backgroundColor: "#1a2123", 
                        border: "1px solid rgba(255,255,255,0.08)",
                        borderRadius: "4px"
                      }}
                      itemStyle={{ color: "#00d9ff" }}
                    />
                    <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                      {shapValues.map((entry: any, index: number) => (
                        <Cell 
                          key={`cell-${index}`} 
                          fill={entry.value > 0 ? "#ffb4ab" : "#00d9ff"} 
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="h-[200px] flex items-center justify-center bg-[#080f11] rounded border border-[rgba(255,255,255,0.08)]">
                <p className="text-[#859398] flex items-center gap-2">
                  <span className="material-symbols-outlined">analytics</span>
                  No SHAP values available for this incident.
                </p>
              </div>
            )}

            {incident.explanation && (
              <div className="mt-6 bg-[#080f11] p-4 rounded border-l-4 border-l-[#00d9ff] border-y border-r border-y-[rgba(255,255,255,0.08)] border-r-[rgba(255,255,255,0.08)]">
                <h3 className="text-[#00d9ff] text-sm uppercase tracking-widest mb-2 font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-sm">robot_2</span>
                  System Conclusion
                </h3>
                <p className="text-[#dde4e6] leading-relaxed font-mono text-sm">
                  {incident.explanation}
                </p>
              </div>
            )}
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
