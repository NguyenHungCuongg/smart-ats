// Progress events for the signed-in user over SSE (ADR-0003, SAD §4.3).

import { useEffect, useEffectEvent } from "react";

import { API_URL, apiFetch } from "./auth";

const RECONNECT_MS = 1000;

type Subscriber = { type: string; onEvent: (data: unknown) => void; onOpen?: () => void };

// One stream per tab, shared by every subscriber: the server caps the streams of a user.
const subscribers = new Set<Subscriber>();
let source: EventSource | null = null;
// The event types the open stream already dispatches.
let listening = new Set<string>();
let connecting = false;
let retry: ReturnType<typeof setTimeout> | undefined;

function listen(type: string) {
  if (!source || listening.has(type)) return;
  listening.add(type);
  source.addEventListener(type, (e) => {
    const data = JSON.parse(e.data);
    for (const s of subscribers) if (s.type === type) s.onEvent(data);
  });
}

function close() {
  clearTimeout(retry);
  source?.close();
  source = null;
}

function reconnect() {
  close();
  retry = setTimeout(connect, RECONNECT_MS);
}

async function connect() {
  if (connecting || source || subscribers.size === 0) return;
  connecting = true;
  // EventSource cannot send the access token, so it is traded for a one-time ticket first.
  const response = await apiFetch("/api/events/ticket", { method: "POST" }).catch(() => null);
  const ticket = response?.ok ? (await response.json()).ticket : null;
  connecting = false;
  if (subscribers.size === 0 || response?.status === 401) return; // unsubscribed, or signed out
  if (!ticket) return reconnect();
  source = new EventSource(`${API_URL}/api/events?ticket=${encodeURIComponent(ticket)}`);
  listening = new Set();
  for (const s of subscribers) listen(s.type);
  // The server listens before it answers, so what a subscriber reloads now misses no event
  // (SAD §6): neither one sent while the stream was down nor one racing the first open.
  source.onopen = () => {
    for (const s of subscribers) s.onOpen?.();
  };
  // The browser's own retry would reuse the spent ticket and get 401: retry with a new one.
  source.onerror = reconnect;
}

/**
 * Delivers the data of each `type` event on the tab's stream, and calls `onOpen` each time the
 * stream opens; returns an unsubscribe.
 */
export function subscribe(
  type: string,
  onEvent: (data: unknown) => void,
  onOpen?: () => void,
): () => void {
  const subscriber = { type, onEvent, onOpen };
  subscribers.add(subscriber);
  listen(type);
  connect();
  return () => {
    subscribers.delete(subscriber);
    if (subscribers.size === 0) close();
  };
}

/**
 * Calls onEvent with the data of each `type` event while the component is mounted, and onOpen
 * each time the stream (re)opens: the moment to reload whatever events may have been missed.
 */
export function useProgressEvents(
  type: string,
  onEvent: (data: unknown) => void,
  onOpen: () => void = () => {},
): void {
  const handle = useEffectEvent(onEvent);
  const opened = useEffectEvent(onOpen);
  useEffect(() => subscribe(type, handle, opened), [type]);
}
