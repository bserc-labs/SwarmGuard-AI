import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/shared/GlassCard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { api, type SystemSettings } from "@/services/api";
import { toast } from "sonner";

export default function SettingsPage() {
  const queryClient = useQueryClient();

  const { data: storedSettings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
  });

  const updateSettingsMutation = useMutation({
    mutationFn: (newSettings: Partial<SystemSettings>) => api.updateSettings(newSettings),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      toast.success("System configuration updated.");
    },
    onError: () => {
      toast.error("Failed to update system configuration.");
    }
  });

  const [criticalThreshold, setCriticalThreshold] = useState<number>(0.85);
  const [highThreshold, setHighThreshold] = useState<number>(0.60);
  const [refreshRate, setRefreshRate] = useState<string>("5s");
  const [uiSound, setUiSound] = useState<boolean>(true);
  const [pushNotif, setPushNotif] = useState<boolean>(false);
  const [webhooks, setWebhooks] = useState<boolean>(true);

  // Sync state when data loads
  useEffect(() => {
    if (storedSettings) {
      setCriticalThreshold(storedSettings.critical_threshold);
      setHighThreshold(storedSettings.high_threshold);
      setRefreshRate(storedSettings.refresh_rate);
      setUiSound(storedSettings.ui_sound);
      setPushNotif(storedSettings.push_notif);
      setWebhooks(storedSettings.webhooks);
    }
  }, [storedSettings]);

  const handleUpdate = (key: keyof SystemSettings, value: any) => {
    // Optimistic local update for quick UX
    if (key === "critical_threshold") setCriticalThreshold(value);
    if (key === "high_threshold") setHighThreshold(value);
    if (key === "refresh_rate") setRefreshRate(value);
    if (key === "ui_sound") setUiSound(value);
    if (key === "push_notif") setPushNotif(value);
    if (key === "webhooks") setWebhooks(value);

    // Send to backend
    updateSettingsMutation.mutate({ [key]: value });
  };

  if (isLoading) {
    return (
      <div className="flex h-[calc(100vh-200px)] items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-5xl mx-auto text-[#dde4e6]">
      <div className="mb-8 border-b border-[rgba(255,255,255,0.08)] pb-4">
        <h1 className="text-3xl font-mono tracking-widest text-[#00d9ff] uppercase flex items-center">
          <span className="material-symbols-outlined mr-3 text-4xl">settings_system_daydream</span>
          System Configuration
        </h1>
        <p className="text-[#859398] font-mono mt-2">Adjust SwarmGuard global parameters and detection heuristics</p>
      </div>

      <div className="space-y-8">
        {/* Category 1: System Thresholds */}
        <GlassCard className="p-6">
          <h3 className="text-xl font-mono tracking-widest text-[#ffdeaa] mb-6 flex items-center border-b border-[rgba(255,255,255,0.05)] pb-3">
            <span className="material-symbols-outlined mr-3">tune</span>
            System Thresholds
          </h3>
          
          <div className="space-y-8">
            <div>
              <div className="flex justify-between items-center mb-2 font-mono">
                <label className="text-sm uppercase tracking-wider text-[#bbc9ce]">Critical Anomaly Threshold</label>
                <span className="text-[#ffb4ab] font-bold">{criticalThreshold.toFixed(2)}</span>
              </div>
              <input 
                type="range" 
                min="0" max="1" step="0.01" 
                value={criticalThreshold}
                onChange={(e) => setCriticalThreshold(parseFloat(e.target.value))}
                onMouseUp={(e) => handleUpdate("critical_threshold", parseFloat((e.target as HTMLInputElement).value))}
                className="w-full accent-[#ffb4ab] h-2 bg-[#080f11] rounded-lg appearance-none cursor-pointer"
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-2 font-mono">
                <label className="text-sm uppercase tracking-wider text-[#bbc9ce]">High Anomaly Threshold</label>
                <span className="text-[#ffdeaa] font-bold">{highThreshold.toFixed(2)}</span>
              </div>
              <input 
                type="range" 
                min="0" max="1" step="0.01" 
                value={highThreshold}
                onChange={(e) => setHighThreshold(parseFloat(e.target.value))}
                onMouseUp={(e) => handleUpdate("high_threshold", parseFloat((e.target as HTMLInputElement).value))}
                className="w-full accent-[#ffdeaa] h-2 bg-[#080f11] rounded-lg appearance-none cursor-pointer"
              />
            </div>
          </div>
        </GlassCard>

        {/* Category 2: Telemetry Configuration */}
        <GlassCard className="p-6">
          <h3 className="text-xl font-mono tracking-widest text-[#00d9ff] mb-6 flex items-center border-b border-[rgba(255,255,255,0.05)] pb-3">
            <span className="material-symbols-outlined mr-3">satellite_alt</span>
            Telemetry Configuration
          </h3>
          
          <div>
            <label className="text-sm uppercase tracking-wider text-[#bbc9ce] block mb-4 font-mono">Data Refresh Rate</label>
            <div className="flex space-x-4">
              {['1s', '5s', '10s', '30s'].map((rate) => (
                <button
                  key={rate}
                  onClick={() => handleUpdate("refresh_rate", rate)}
                  className={`px-6 py-2 rounded font-mono font-bold transition-all border ${
                    refreshRate === rate 
                    ? 'bg-[rgba(0,217,255,0.15)] text-[#00d9ff] border-[#00d9ff] shadow-[0_0_10px_rgba(0,217,255,0.3)]' 
                    : 'bg-[#080f11] text-[#859398] border-[rgba(255,255,255,0.1)] hover:border-[#00d9ff] hover:text-[#00d9ff]'
                  }`}
                >
                  {rate}
                </button>
              ))}
            </div>
          </div>
        </GlassCard>

        {/* Category 3: Notifications */}
        <GlassCard className="p-6">
          <h3 className="text-xl font-mono tracking-widest text-[#00d9ff] mb-6 flex items-center border-b border-[rgba(255,255,255,0.05)] pb-3">
            <span className="material-symbols-outlined mr-3">notifications_active</span>
            Alert Systems
          </h3>
          
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-mono uppercase tracking-wider text-sm text-[#bbc9ce]">UI Sound Effects</div>
                <div className="text-xs text-[#859398] mt-1">Tactical feedback audio for interface interactions</div>
              </div>
              <button 
                onClick={() => handleUpdate("ui_sound", !uiSound)}
                className={`w-14 h-7 rounded-full transition-colors relative flex items-center ${uiSound ? 'bg-[#00d9ff] shadow-[0_0_10px_rgba(0,217,255,0.5)]' : 'bg-[#080f11] border border-[rgba(255,255,255,0.2)]'}`}
              >
                <div className={`w-5 h-5 rounded-full bg-white transition-transform absolute ${uiSound ? 'translate-x-8' : 'translate-x-1'}`} />
              </button>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <div className="font-mono uppercase tracking-wider text-sm text-[#bbc9ce]">Desktop Push Notifications</div>
                <div className="text-xs text-[#859398] mt-1">Receive alerts outside the command center view</div>
              </div>
              <button 
                onClick={() => handleUpdate("push_notif", !pushNotif)}
                className={`w-14 h-7 rounded-full transition-colors relative flex items-center ${pushNotif ? 'bg-[#00d9ff] shadow-[0_0_10px_rgba(0,217,255,0.5)]' : 'bg-[#080f11] border border-[rgba(255,255,255,0.2)]'}`}
              >
                <div className={`w-5 h-5 rounded-full bg-white transition-transform absolute ${pushNotif ? 'translate-x-8' : 'translate-x-1'}`} />
              </button>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <div className="font-mono uppercase tracking-wider text-sm text-[#bbc9ce]">External Webhooks</div>
                <div className="text-xs text-[#859398] mt-1">Relay incident data to external response systems</div>
              </div>
              <button 
                onClick={() => handleUpdate("webhooks", !webhooks)}
                className={`w-14 h-7 rounded-full transition-colors relative flex items-center ${webhooks ? 'bg-[#00d9ff] shadow-[0_0_10px_rgba(0,217,255,0.5)]' : 'bg-[#080f11] border border-[rgba(255,255,255,0.2)]'}`}
              >
                <div className={`w-5 h-5 rounded-full bg-white transition-transform absolute ${webhooks ? 'translate-x-8' : 'translate-x-1'}`} />
              </button>
            </div>
          </div>
        </GlassCard>

        {/* Category 4: About System */}
        <GlassCard className="p-6">
          <h3 className="text-xl font-mono tracking-widest text-[#00d9ff] mb-6 flex items-center border-b border-[rgba(255,255,255,0.05)] pb-3">
            <span className="material-symbols-outlined mr-3">info</span>
            System Information
          </h3>
          <div className="grid grid-cols-2 gap-4 font-mono text-sm">
            <div className="bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)]">
              <div className="text-xs text-[#859398] uppercase tracking-wider mb-1">Platform</div>
              <div className="text-[#dde4e6]">SwarmGuard-AI v2.0</div>
            </div>
            <div className="bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)]">
              <div className="text-xs text-[#859398] uppercase tracking-wider mb-1">AI Engine</div>
              <div className="text-[#dde4e6]">Isolation Forest + SHAP</div>
            </div>
            <div className="bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)]">
              <div className="text-xs text-[#859398] uppercase tracking-wider mb-1">Backend</div>
              <div className="text-[#dde4e6]">FastAPI + SQLite</div>
            </div>
            <div className="bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)]">
              <div className="text-xs text-[#859398] uppercase tracking-wider mb-1">Security</div>
              <div className="text-[#dde4e6]">JWT + RBAC + API-Key Auth</div>
            </div>
            <div className="bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)]">
              <div className="text-xs text-[#859398] uppercase tracking-wider mb-1">Team</div>
              <div className="text-[#dde4e6]">BSERC Labs</div>
            </div>
            <div className="bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)]">
              <div className="text-xs text-[#859398] uppercase tracking-wider mb-1">Keyboard Shortcuts</div>
              <div className="text-[#dde4e6]">Alt+E / Alt+R / Alt+S</div>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
