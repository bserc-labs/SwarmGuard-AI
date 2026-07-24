import React from 'react';
import { Link } from '@tanstack/react-router';

export default function NotFoundPage() {
  return (
    <div className="relative min-h-screen w-full bg-[#080f11] grid-bg flex flex-col items-center justify-center overflow-hidden">
      
      {/* Massive semi-transparent 404 behind */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none select-none overflow-hidden">
        <span className="text-[30vw] font-bold text-white/[0.02] font-mono tracking-tighter leading-none">
          404
        </span>
      </div>

      {/* Radar sweep animation */}
      <div className="absolute w-[600px] h-[600px] rounded-full border border-[#00d9ff]/10 opacity-30 flex items-center justify-center pointer-events-none">
        <div className="absolute w-full h-full rounded-full radar-scan border-t-2 border-[#00d9ff]/50"></div>
        <div className="w-[400px] h-[400px] rounded-full border border-[#00d9ff]/10"></div>
        <div className="w-[200px] h-[200px] rounded-full border border-[#00d9ff]/10 absolute"></div>
        <div className="w-3 h-3 rounded-full bg-[#00d9ff] absolute shadow-[0_0_15px_#00d9ff]"></div>
      </div>

      {/* Content */}
      <div className="relative z-10 flex flex-col items-center text-center space-y-6">
        <div className="w-20 h-20 rounded-full bg-[#ffb4ab]/10 border border-[#ffb4ab]/30 flex items-center justify-center mb-2">
          <span className="material-symbols-outlined text-[#ffb4ab] text-4xl">warning</span>
        </div>
        
        <h1 className="text-5xl md:text-7xl font-bold text-[#dde4e6] tracking-widest font-mono animate-glitch relative">
          <span className="relative z-10">SIGNAL LOST</span>
        </h1>
        
        <p className="text-[#859398] font-mono text-lg max-w-md mt-4 border-l-2 border-[#00d9ff] pl-4 text-left">
          Target frequency not found.<br/>
          Check your coordinates.
        </p>

        <div className="pt-8">
          <Link
            to="/dashboard"
            className="group relative inline-flex items-center gap-3 px-8 py-3 bg-transparent border border-[#00d9ff]/50 text-[#00d9ff] font-mono text-sm uppercase tracking-widest overflow-hidden transition-all hover:bg-[#00d9ff]/10 hover:border-[#00d9ff] hover:shadow-[0_0_20px_rgba(0,217,255,0.2)]"
          >
            <span className="material-symbols-outlined text-[20px] transition-transform group-hover:-translate-x-1">arrow_back</span>
            Return to Dashboard
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-[#00d9ff]/10 to-transparent -translate-x-full group-hover:animate-[shimmer_1.5s_infinite]"></div>
          </Link>
        </div>
      </div>
    </div>
  );
}
