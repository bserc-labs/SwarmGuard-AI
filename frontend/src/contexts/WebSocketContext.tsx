import React, { createContext, useContext, useEffect, useRef, useState, useCallback, type ReactNode } from "react";
import { createWebSocket } from "@/services/websocket";
import type { DetectionResult } from "@/services/api";

interface WebSocketContextType {
  isConnected: boolean;
  alerts: DetectionResult[];
  lastAlert: DetectionResult | null;
  connect: () => void;
  disconnect: () => void;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [isConnected, setIsConnected] = useState(false);
  const [alerts, setAlerts] = useState<DetectionResult[]>([]);
  const [lastAlert, setLastAlert] = useState<DetectionResult | null>(null);
  const wsRef = useRef<ReturnType<typeof createWebSocket> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current) return;

    wsRef.current = createWebSocket({
      onMessage: (data) => {
        const alert = data as DetectionResult;
        setLastAlert(alert);
        setAlerts((prev) => [alert, ...prev].slice(0, 100));
      },
      onStatusChange: setIsConnected,
    });
  }, []);

  const disconnect = useCallback(() => {
    wsRef.current?.disconnect();
    wsRef.current = null;
    setIsConnected(false);
  }, []);

  useEffect(() => {
    connect();
    return disconnect;
  }, [connect, disconnect]);

  return (
    <WebSocketContext.Provider value={{ isConnected, alerts, lastAlert, connect, disconnect }}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocketContext(): WebSocketContextType {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error("useWebSocketContext must be used within WebSocketProvider");
  return ctx;
}
