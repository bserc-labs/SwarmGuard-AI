import { createFileRoute, Link } from "@tanstack/react-router";
import { screens } from "@/lib/screens";

export const Route = createFileRoute("/launcher")({
  head: () => ({
    meta: [
      { title: "Launcher · SwarmGuard-AI" },
      {
        name: "description",
        content: "Directory of every SwarmGuard-AI operator terminal.",
      },
      { property: "og:title", content: "Launcher · SwarmGuard-AI" },
      {
        property: "og:description",
        content: "Directory of every SwarmGuard-AI operator terminal.",
      },
    ],
  }),
  component: Launcher,
});

function Launcher() {
  const grouped = screens.reduce<Record<string, typeof screens>>((acc, s) => {
    (acc[s.category] ||= []).push(s);
    return acc;
  }, {});

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-[#080f11] text-[#dde4e6]">
      <div className="pointer-events-none absolute inset-0">
        <div
          className="absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              "linear-gradient(rgba(0,217,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(0,217,255,0.05) 1px, transparent 1px)",
            backgroundSize: "50px 50px",
            transform: "scale(1.5) rotate(-12deg) translateY(-20%)",
          }}
        />
        <div className="absolute -top-[10%] -left-[10%] h-[40%] w-[40%] rounded-full bg-[#00d9ff]/10 blur-[120px]" />
        <div className="absolute -bottom-[10%] -right-[10%] h-[40%] w-[40%] rounded-full bg-[#0053db]/10 blur-[120px]" />
      </div>

      <div className="relative z-10 mx-auto max-w-6xl px-6 py-16">
        <header className="mb-14 flex items-end justify-between gap-6">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded border border-[#00d9ff]/30 bg-[#00d9ff]/10 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-[#00d9ff]">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#ffbb2a]" />
              System Online
            </div>
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">SwarmGuard-AI</h1>
            <p className="mt-3 max-w-xl text-sm text-[#bbc9ce] sm:text-base">
              Screen directory. Every operator terminal in one place.
            </p>
          </div>
          <Link
            to="/screens/$slug"
            params={{ slug: "secure_login" }}
            className="rounded border border-[#00d9ff]/40 bg-[#00d9ff]/10 px-4 py-2 text-xs font-bold uppercase tracking-widest text-[#00d9ff] hover:bg-[#00d9ff]/20"
          >
            Enter Console →
          </Link>
        </header>

        <div className="space-y-12">
          {Object.entries(grouped).map(([category, items]) => (
            <section key={category}>
              <div className="mb-4 flex items-center gap-3">
                <h2 className="text-xs font-bold uppercase tracking-[0.25em] text-[#00d9ff]">
                  {category}
                </h2>
                <div className="h-px flex-1 bg-gradient-to-r from-[#00d9ff]/40 to-transparent" />
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((s) => (
                  <Link
                    key={s.slug}
                    to="/screens/$slug"
                    params={{ slug: s.slug }}
                    className="group relative overflow-hidden rounded-xl border border-white/10 bg-[#0e1417]/70 p-5 backdrop-blur transition-all hover:border-[#00d9ff]/50 hover:shadow-[0_0_30px_rgba(0,217,255,0.15)]"
                  >
                    <div className="mb-8 flex items-start justify-between">
                      <div className="font-mono text-[10px] uppercase tracking-widest text-[#859398]">
                        //{s.slug}
                      </div>
                      <span className="text-[#00d9ff] opacity-0 transition-opacity group-hover:opacity-100">
                        →
                      </span>
                    </div>
                    <h3 className="text-base font-semibold text-[#dde4e6] group-hover:text-[#afecff]">
                      {s.title}
                    </h3>
                    <p className="mt-1 text-sm text-[#bbc9ce]">{s.description}</p>
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
