import { Outlet, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useAuth } from "@/hooks/useAuth";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WebSocketProvider } from "@/contexts/WebSocketContext";
import { AlertBanner } from "@/components/AlertBanner";

export function AppLayout() {
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();

  useEffect(() => {
    if (!isLoggedIn) {
      navigate({ to: "/login" });
    }
  }, [isLoggedIn, navigate]);

  if (!isLoggedIn) return null;

  return (
    <WebSocketProvider>
      <div className="min-h-screen bg-sg-bg grid-bg relative">
        <AlertBanner />
        <Sidebar />
        <div className="ml-[280px] flex flex-col min-h-screen">
          <Header />
          <main className="flex-1 p-6 overflow-y-auto">
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </WebSocketProvider>
  );
}
