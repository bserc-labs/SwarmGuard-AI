import { useEffect, useRef, useState, useCallback } from "react";
import { createWebSocket } from "@/services/websocket";
import type { DetectionResult } from "@/services/api";

export function useWebSocket() {
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

  return { isConnected, alerts, lastAlert, connect, disconnect };
}
