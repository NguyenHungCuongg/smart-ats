import { afterEach, beforeEach, expect, test, vi } from "vitest";

type Events = typeof import("./events");

/** Records every EventSource the module opens; tests fire events and errors on them. */
class FakeEventSource {
  static opened: FakeEventSource[] = [];
  listeners = new Map<string, (e: MessageEvent) => void>();
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.opened.push(this);
  }
  addEventListener(type: string, listener: (e: MessageEvent) => void) {
    this.listeners.set(type, listener);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}

let tickets = 0;
let events: Events;

beforeEach(async () => {
  tickets = 0;
  FakeEventSource.opened = [];
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) =>
      `${init.method} ${url}` === "POST /api/events/ticket"
        ? Response.json({ ticket: `ticket-${++tickets}` })
        : new Response(null, { status: 404 }),
    ),
  );
  vi.resetModules();
  events = await import("./events");
});

afterEach(() => {
  vi.useRealTimers();
});

/** Lets the ticket request settle, so the EventSource is open. */
const opened = () => vi.advanceTimersByTimeAsync(0);

test("opens the stream with a fresh ticket and delivers events of the given type", async () => {
  const received: unknown[] = [];
  events.subscribe("progress", (data) => received.push(data));
  await opened();

  const [source] = FakeEventSource.opened;
  expect(source.url).toBe("/api/events?ticket=ticket-1");
  source.emit("progress", { done: 1 });
  source.emit("other", { done: 2 });
  expect(received).toEqual([{ done: 1 }]);
});

test("after an error, reconnects with a new ticket: the old one is spent", async () => {
  events.subscribe("progress", () => {});
  await opened();

  FakeEventSource.opened[0].onerror?.();
  await vi.advanceTimersByTimeAsync(5000);

  expect(FakeEventSource.opened[0].closed).toBe(true);
  expect(FakeEventSource.opened.map((s) => s.url)).toEqual([
    "/api/events?ticket=ticket-1",
    "/api/events?ticket=ticket-2",
  ]);
});

test("keeps retrying while the API is unreachable, but not once signed out", async () => {
  const fetch = vi.mocked(globalThis.fetch);
  fetch
    .mockRejectedValueOnce(new TypeError("network"))
    .mockResolvedValueOnce(new Response(null, { status: 502 }));
  events.subscribe("progress", () => {});
  await vi.advanceTimersByTimeAsync(5000);
  expect(FakeEventSource.opened.map((s) => s.url)).toEqual(["/api/events?ticket=ticket-1"]);

  fetch.mockImplementation(async () => new Response(null, { status: 401 }));
  const before = fetch.mock.calls.length;
  FakeEventSource.opened[0].onerror?.();
  await vi.advanceTimersByTimeAsync(5000);
  expect(FakeEventSource.opened).toHaveLength(1);
  // One ticket request and apiFetch's one refresh attempt, then nothing.
  expect(fetch.mock.calls.length - before).toBe(2);
});

test("unsubscribing closes the stream and stops reconnecting", async () => {
  const unsubscribe = events.subscribe("progress", () => {});
  await opened();

  FakeEventSource.opened[0].onerror?.();
  unsubscribe();
  await vi.advanceTimersByTimeAsync(5000);

  expect(FakeEventSource.opened).toHaveLength(1);
  expect(FakeEventSource.opened[0].closed).toBe(true);
});
