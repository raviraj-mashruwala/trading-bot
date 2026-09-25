import type { WsEvent } from "@/types";

export function createWsManager(url: string, onEvent: (event: WsEvent) => void) {
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelay = 1000;
  let intentionalClose = false;

  function connect() {
    intentionalClose = false;
    socket = new WebSocket(url);

    socket.onopen = () => {
      reconnectDelay = 1000;
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
  }

  return {
    connect,
    disconnect,
    get isConnected() {
      return socket?.readyState === WebSocket.OPEN;
    },
  };
}
