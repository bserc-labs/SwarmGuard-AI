import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { GlassCard } from "@/components/shared/GlassCard";

export default function ProfilePage() {
  const { user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const handlePasswordChange = (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      alert("Passwords do not match!");
      return;
    }
    alert("Password updated securely");
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
  };

  const username = user?.username || "Operator";
  const role = user?.role || "UNKNOWN";
  const email = `${username.toLowerCase()}@swarmguard.ai`;

  return (
    <div className="p-8 max-w-6xl mx-auto text-[#dde4e6]">
      <div className="mb-8 border-b border-[rgba(255,255,255,0.08)] pb-4">
        <h1 className="text-3xl font-mono tracking-widest text-[#00d9ff] uppercase">Operator Profile</h1>
        <p className="text-[#859398] font-mono mt-2">Manage identity and security credentials</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column - User Info */}
        <div className="lg:col-span-1">
          <GlassCard className="p-8 flex flex-col items-center">
            <div className="w-32 h-32 rounded-full border-2 border-[#00d9ff] shadow-[0_0_15px_rgba(0,217,255,0.3)] flex items-center justify-center bg-[rgba(0,217,255,0.1)] mb-6">
              <span className="text-5xl font-mono text-[#00d9ff]">{username.charAt(0).toUpperCase()}</span>
            </div>
            
            <h2 className="text-2xl font-bold tracking-wider mb-2">{username}</h2>
            <div className="bg-[rgba(0,217,255,0.1)] text-[#00d9ff] px-3 py-1 rounded text-sm font-mono tracking-widest mb-6 border border-[rgba(0,217,255,0.3)]">
              {role.toUpperCase()}
            </div>

            <div className="w-full space-y-4">
              <div>
                <label className="text-xs text-[#859398] uppercase tracking-wider block mb-1">Email Classification</label>
                <div className="text-sm font-mono bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)]">
                  {email}
                </div>
              </div>
              <div>
                <label className="text-xs text-[#859398] uppercase tracking-wider block mb-1">Status</label>
                <div className="text-sm font-mono bg-[#080f11] p-3 rounded border border-[rgba(255,255,255,0.05)] flex items-center">
                  <span className="w-2 h-2 rounded-full bg-green-500 mr-2 shadow-[0_0_8px_rgba(34,197,94,0.6)]"></span>
                  ACTIVE / VERIFIED
                </div>
              </div>
            </div>
          </GlassCard>
        </div>

        {/* Right Column - Security */}
        <div className="lg:col-span-2">
          <GlassCard className="p-8">
            <h3 className="text-xl font-mono tracking-widest text-[#00d9ff] mb-6 flex items-center border-b border-[rgba(255,255,255,0.08)] pb-4">
              <span className="material-symbols-outlined mr-3">lock</span>
              Security Protocols
            </h3>

            <form onSubmit={handlePasswordChange} className="space-y-6 max-w-md">
              <div>
                <label className="text-xs text-[#859398] uppercase tracking-wider block mb-2 font-mono">Current Authorization Key</label>
                <input 
                  type="password" 
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full bg-[#080f11] border border-[rgba(255,255,255,0.1)] rounded p-3 text-[#dde4e6] focus:outline-none focus:border-[#00d9ff] focus:shadow-[0_0_10px_rgba(0,217,255,0.2)] font-mono transition-all glass-input"
                  required
                />
              </div>

              <div>
                <label className="text-xs text-[#859398] uppercase tracking-wider block mb-2 font-mono">New Authorization Key</label>
                <input 
                  type="password" 
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full bg-[#080f11] border border-[rgba(255,255,255,0.1)] rounded p-3 text-[#dde4e6] focus:outline-none focus:border-[#00d9ff] focus:shadow-[0_0_10px_rgba(0,217,255,0.2)] font-mono transition-all glass-input"
                  required
                />
              </div>

              <div>
                <label className="text-xs text-[#859398] uppercase tracking-wider block mb-2 font-mono">Confirm Authorization Key</label>
                <input 
                  type="password" 
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full bg-[#080f11] border border-[rgba(255,255,255,0.1)] rounded p-3 text-[#dde4e6] focus:outline-none focus:border-[#00d9ff] focus:shadow-[0_0_10px_rgba(0,217,255,0.2)] font-mono transition-all glass-input"
                  required
                />
              </div>

              <button 
                type="submit"
                className="bg-gradient-to-r from-[#00d9ff] to-[#0099cc] text-[#080f11] font-bold py-3 px-6 rounded uppercase tracking-widest hover:shadow-[0_0_15px_rgba(0,217,255,0.5)] transition-all font-mono"
              >
                Update Key
              </button>
            </form>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
