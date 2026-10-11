import type { WsEvent } from "@/types";

export type WsStatus = "connected" | "reconnecting" | "disconnected";

export function createWsManager(
  url: string,
  onEvent: (event: WsEvent) => void,
  onStatusChange?: (status: WsStatus) => void,
) {
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelay = 1000;
  let intentionalClose = false;

  function connect() {
    intentionalClose = false;
    try {
      socket = new WebSocket(url);
    } catch {
      onStatusChange?.("disconnected");
      return;
    }

    socket.onopen = () => {
      reconnectDelay = 1000;
      onStatusChange?.("connected");
    };

    socket.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed.type === "pong") return;
        onEvent(parsed as WsEvent);
      } catch {
        // ignore malformed JSON
      }
    };

    socket.onclose = () => {
      if (!intentionalClose) {
        onStatusChange?.("reconnecting");
        reconnectTimer = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 2, 30000);
          connect();
        }, reconnectDelay);
      }
    };

    socket.onerror = () => {
      socket?.close();
    };
  }

  function disconnect() {
    intentionalClose = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    socket?.close();
    socket = null;
    onStatusChange?.("disconnected");
  }

  return {
    connect,
    disconnect,
    get isConnected() {
      return socket?.readyState === WebSocket.OPEN;
    },
  };
}
