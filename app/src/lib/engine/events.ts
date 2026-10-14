import type { EngineEvent } from "./types";

export type StreamState = "connecting" | "open" | "closed";

type Listener = (event: EngineEvent) => void;
type StateListener = (state: StreamState) => void;

interface ServerMessage {
  type: string;
  event?: EngineEvent;
}

const MAX_BACKOFF_MS = 8000;

/**
 * Flux d'événements du moteur. S'authentifie par le premier message,
 * se reconnecte seul avec un délai croissant.
 */
export class EventStream {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private stateListeners = new Set<StateListener>();
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  state: StreamState = "connecting";

  constructor(
    private readonly url: string,
    private readonly token: string,
    private readonly createSocket: (url: string) => WebSocket = (u) => new WebSocket(u),
  ) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.socket?.close();
    this.socket = null;
    this.setState("closed");
  }

  onEvent(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onState(listener: StateListener): () => void {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  private setState(state: StreamState): void {
    if (this.state === state) return;
    this.state = state;
    for (const listener of this.stateListeners) listener(state);
  }

  private connect(): void {
    this.setState("connecting");
    const socket = this.createSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "auth", token: this.token }));
    };
    socket.onmessage = (message: MessageEvent<string>) => {
      let data: ServerMessage;
      try {
        data = JSON.parse(message.data) as ServerMessage;
      } catch {
        return;
      }
      if (data.type === "hello") {
        this.attempt = 0;
        this.setState("open");
      } else if (data.type === "event" && data.event) {
        for (const listener of this.listeners) listener(data.event);
      }
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.setState("closed");
      if (!this.stopped) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** this.attempt);
    this.attempt += 1;
    this.timer = setTimeout(() => {
      this.connect();
    }, delay);
  }
}
