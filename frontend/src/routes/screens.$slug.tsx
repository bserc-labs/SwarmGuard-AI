import { createFileRoute, Link, notFound, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { findScreen, screens } from "@/lib/screens";

export const Route = createFileRoute("/screens/$slug")({
  loader: ({ params }) => {
    const screen = findScreen(params.slug);
    if (!screen) throw notFound();
    return { screen };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.screen.title} · SwarmGuard-AI`
          : "SwarmGuard-AI",
      },
      {
        name: "description",
        content: loaderData?.screen.description ?? "SwarmGuard-AI operator terminal.",
      },
      {
        property: "og:title",
        content: loaderData
          ? `${loaderData.screen.title} · SwarmGuard-AI`
          : "SwarmGuard-AI",
      },
      {
        property: "og:description",
        content: loaderData?.screen.description ?? "SwarmGuard-AI operator terminal.",
      },
    ],
  }),
  component: ScreenViewer,
  notFoundComponent: () => (
    <div className="flex min-h-screen items-center justify-center bg-[#0e1417] text-[#dde4e6]">
      <div className="text-center">
        <p className="text-sm uppercase tracking-widest text-[#bbc9ce]">Screen not found</p>
        <Link
          to="/screens/$slug"
          params={{ slug: "signal_lost_404" }}
          className="mt-4 inline-block text-[#00d9ff] underline"
        >
          View 404 terminal
        </Link>
      </div>
    </div>
  ),
});

function ScreenViewer() {
  const { screen } = Route.useLoaderData();
  const navigate = useNavigate();
  const isLogin = screen.slug === "secure_login";
  const currentIndex = screens.findIndex((s) => s.slug === screen.slug);
  const prev = currentIndex > 0 ? screens[currentIndex - 1] : null;
  const next = currentIndex < screens.length - 1 ? screens[currentIndex + 1] : null;

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      const data = ev.data as { type?: string; slug?: string } | null;
      if (!data || data.type !== "swarmguard:navigate" || !data.slug) return;
      if (!findScreen(data.slug)) return;
      navigate({ to: "/screens/$slug", params: { slug: data.slug } });
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [navigate]);

  return (
    <div className="fixed inset-0 flex flex-col bg-[#080f11] text-[#dde4e6]">
      {!isLogin && (
        <header className="flex items-center justify-between gap-4 border-b border-white/10 bg-[#0e1417]/90 px-4 py-2 text-xs uppercase tracking-widest backdrop-blur">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              to="/launcher"
              className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[#bbc9ce] hover:border-[#00d9ff]/60 hover:text-[#00d9ff]"
            >
              ☰ Launcher
            </Link>
            <Link
              to="/screens/$slug"
              params={{ slug: "secure_login" }}
              className="hidden sm:inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[#bbc9ce] hover:border-[#ffb4ab]/60 hover:text-[#ffb4ab]"
            >
              ⏻ Sign out
            </Link>
            <span className="hidden sm:inline text-[#3c494d]">/</span>
            <span className="truncate text-[#bbc9ce]">
              <span className="text-[#00d9ff]">{screen.category}</span>
              <span className="mx-2 text-[#3c494d]">·</span>
              <span className="font-semibold normal-case tracking-normal text-[#dde4e6]">
                {screen.title}
              </span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            {prev && (
              <Link
                to="/screens/$slug"
                params={{ slug: prev.slug }}
                className="rounded border border-white/10 px-2 py-1 text-[#bbc9ce] hover:border-[#00d9ff]/60 hover:text-[#00d9ff]"
              >
                ← Prev
              </Link>
            )}
            {next && (
              <Link
                to="/screens/$slug"
                params={{ slug: next.slug }}
                className="rounded border border-white/10 px-2 py-1 text-[#bbc9ce] hover:border-[#00d9ff]/60 hover:text-[#00d9ff]"
              >
                Next →
              </Link>
            )}
          </div>
        </header>
      )}
      <iframe
        key={screen.slug}
        src={`/screens/${screen.slug}.html`}
        title={screen.title}
        className="w-full flex-1 border-0 bg-[#0e1417]"
      />
    </div>
  );
}
