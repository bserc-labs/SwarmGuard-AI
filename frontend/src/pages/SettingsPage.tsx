import { useEffect, useState } from "react";
import { GlassCard } from "@/components/shared/GlassCard";

const SETTINGS_STORAGE_KEY = "swarmguard-settings";

function readStoredSettings() {
  if (typeof window === "undefined") return null;

  try {
    const stored = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch {
    return null;
  }
}

export default function SettingsPage() {
  const storedSettings = readStoredSettings();

  const [criticalThreshold, setCriticalThreshold] = useState<number>(storedSettings?.criticalThreshold ?? 0.85);
  const [highThreshold, setHighThreshold] = useState<number>(storedSettings?.highThreshold ?? 0.60);
  const [refreshRate, setRefreshRate] = useState<string>(storedSettings?.refreshRate ?? "5s");
  
  const [uiSound, setUiSound] = useState<boolean>(storedSettings?.uiSound ?? true);
  const [pushNotif, setPushNotif] = useState<boolean>(storedSettings?.pushNotif ?? false);
  const [webhooks, setWebhooks] = useState<boolean>(storedSettings?.webhooks ?? true);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const nextSettings = {
      criticalThreshold,
      highThreshold,
      refreshRate,
      uiSound,
      pushNotif,
      webhooks,
    };

    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(nextSettings));
  }, [criticalThreshold, highThreshold, refreshRate, uiSound, pushNotif, webhooks]);

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
                  onClick={() => setRefreshRate(rate)}
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
                onClick={() => setUiSound(!uiSound)}
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
                onClick={() => setPushNotif(!pushNotif)}
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
                onClick={() => setWebhooks(!webhooks)}
                className={`w-14 h-7 rounded-full transition-colors relative flex items-center ${webhooks ? 'bg-[#00d9ff] shadow-[0_0_10px_rgba(0,217,255,0.5)]' : 'bg-[#080f11] border border-[rgba(255,255,255,0.2)]'}`}
              >
                <div className={`w-5 h-5 rounded-full bg-white transition-transform absolute ${webhooks ? 'translate-x-8' : 'translate-x-1'}`} />
              </button>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
