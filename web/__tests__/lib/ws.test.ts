import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createWsManager } from "@/lib/ws";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  readyState = 0;
  close = vi.fn(() => { this.readyState = 3; });
  static OPEN = 1;
  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }
  simulateOpen() { this.readyState = 1; this.onopen?.(); }
  simulateMessage(data: string) { this.onmessage?.({ data }); }
  simulateClose() { this.readyState = 3; this.onclose?.(); }
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WebSocket manager", () => {
  it("connects and calls onEvent for messages", () => {
    const onEvent = vi.fn();
    const ws = createWsManager("ws://localhost:8000/ws", onEvent);
    ws.connect();
    const instance = MockWebSocket.instances[0];
    instance.simulateOpen();
    instance.simulateMessage(JSON.stringify({ type: "scan.universe", timestamp: "t", data: { count: 5 } }));
    expect(onEvent).toHaveBeenCalledWith({ type: "scan.universe", timestamp: "t", data: { count: 5 } });
  });

  it("disconnect closes the socket", () => {
    const ws = createWsManager("ws://localhost:8000/ws", vi.fn());
    ws.connect();
    MockWebSocket.instances[0].simulateOpen();
    ws.disconnect();
    expect(MockWebSocket.instances[0].close).toHaveBeenCalled();
  });

  it("ignores malformed JSON messages", () => {
    const onEvent = vi.fn();
    const ws = createWsManager("ws://localhost:8000/ws", onEvent);
    ws.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateMessage("not json");
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("handles pong messages without calling onEvent", () => {
    const onEvent = vi.fn();
    const ws = createWsManager("ws://localhost:8000/ws", onEvent);
    ws.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateMessage(JSON.stringify({ type: "pong" }));
    expect(onEvent).not.toHaveBeenCalled();
  });
});
