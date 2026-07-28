import React, { useState, useEffect, useRef, FormEvent } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useAuth } from '@/hooks/useAuth';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  
  const auth = useAuth();
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (auth.isLoggedIn) {
      navigate({ to: '/dashboard' });
    }
  }, [auth.isLoggedIn, navigate]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let particles: { x: number; y: number; vx: number; vy: number }[] = [];

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    
    window.addEventListener('resize', resize);
    resize();

    // Initialize particles
    const particleCount = 70;
    for (let i = 0; i < particleCount; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.5,
        vy: (Math.random() - 0.5) * 0.5,
      });
    }

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#00d9ff';
      ctx.lineWidth = 0.5;

      particles.forEach((p, i) => {
        p.x += p.vx;
        p.y += p.vy;

        if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.5, 0, Math.PI * 2);
        ctx.fill();

        for (let j = i + 1; j < particles.length; j++) {
          const p2 = particles[j];
          const dx = p.x - p2.x;
          const dy = p.y - p2.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < 100) {
            ctx.beginPath();
            ctx.strokeStyle = `rgba(0, 217, 255, ${1 - dist / 100})`;
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
          }
        }
      });

      animationFrameId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await auth.login(username, password);
      navigate({ to: '/dashboard' });
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Please check credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full bg-[#080f11] grid-bg flex items-center justify-center overflow-hidden">
      <canvas
        ref={canvasRef}
        className="absolute inset-0 z-0 pointer-events-none"
      />
      
      <div className="relative z-10 w-full max-w-[440px] px-6 animate-fade-in">
        <div className="glass-card p-8 rounded-2xl flex flex-col items-center shadow-2xl">
          {/* Logo Section */}
          <div className="mb-8 flex flex-col items-center text-center">
            <div className="w-20 h-20 rounded-2xl border border-[#00d9ff]/40 overflow-hidden flex items-center justify-center mb-4 primary-glow bg-[#080f11]/80 shadow-[0_0_20px_rgba(0,217,255,0.4)]">
              <img src="/logo.png" alt="SwarmGuard Logo" className="w-full h-full object-cover" />
            </div>
            <h1 className="text-3xl font-bold text-[#dde4e6] tracking-wider mb-1 font-mono">SwarmGuard</h1>
            <p className="text-[#00d9ff] text-xs font-mono tracking-[0.3em] shimmer-text uppercase">AI SENTINEL</p>
          </div>

          <form onSubmit={handleSubmit} className="w-full space-y-5">
            {error && (
              <div className="w-full p-3 rounded-lg bg-[#ffb4ab]/10 border border-[#ffb4ab]/20 text-[#ffb4ab] text-sm font-mono flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px]">warning</span>
                {error}
              </div>
            )}

            <div className="space-y-4">
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[#859398] text-[20px]">person</span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Operator ID"
                  required
                  className="glass-input w-full bg-[#1a2123]/50 border border-white/10 rounded-lg py-3 pl-10 pr-4 text-[#dde4e6] placeholder:text-[#859398] focus:outline-none focus:border-[#00d9ff]/50 focus:ring-1 focus:ring-[#00d9ff]/50 transition-all font-mono text-sm"
                />
              </div>

              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[#859398] text-[20px]">lock</span>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Passkey"
                  required
                  className="glass-input w-full bg-[#1a2123]/50 border border-white/10 rounded-lg py-3 pl-10 pr-10 text-[#dde4e6] placeholder:text-[#859398] focus:outline-none focus:border-[#00d9ff]/50 focus:ring-1 focus:ring-[#00d9ff]/50 transition-all font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#859398] hover:text-[#dde4e6] transition-colors flex items-center justify-center"
                >
                  <span className="material-symbols-outlined text-[20px]">
                    {showPassword ? 'visibility_off' : 'visibility'}
                  </span>
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3 px-4 rounded-lg bg-gradient-to-r from-[#00d9ff] to-[#005b6c] text-[#080f11] font-bold tracking-widest text-sm uppercase transition-all hover:shadow-[0_0_20px_rgba(0,217,255,0.4)] disabled:opacity-70 disabled:cursor-not-allowed flex items-center justify-center gap-2 mt-4"
            >
              {isLoading ? (
                <>
                  <LoadingSpinner size="sm" color="#080f11" />
                  Authenticating...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>

          {/* Footer Section */}
          <div className="mt-8 pt-6 w-full border-t border-white/5 flex flex-col gap-3 font-mono text-[10px] text-[#859398] uppercase tracking-wider">
            <div className="flex items-center justify-between w-full">
              <span className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
                System Health: Optimal
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[14px]">shield</span>
              Protected by AES-256 Encryption
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
