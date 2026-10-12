// Progress events for the signed-in user over SSE (ADR-0003, SAD §4.3).

import { useEffect, useEffectEvent } from "react";

import { API_URL, apiFetch } from "./auth";

const RECONNECT_MS = 1000;

/** Delivers the data of each `type` event on the user's stream; returns an unsubscribe. */
export function subscribe(type: string, onEvent: (data: unknown) => void): () => void {
  let source: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  function reconnect() {
    source?.close();
    retry = setTimeout(connect, RECONNECT_MS);
  }

  async function connect() {
    // EventSource cannot send the access token, so it is traded for a one-time ticket first.
    const response = await apiFetch("/api/events/ticket", { method: "POST" }).catch(() => null);
    if (stopped || response?.status === 401) return; // signed out
    if (!response?.ok) return reconnect();
    const { ticket } = await response.json();
    if (stopped) return;
    source = new EventSource(`${API_URL}/api/events?ticket=${encodeURIComponent(ticket)}`);
    source.addEventListener(type, (e) => onEvent(JSON.parse(e.data)));
    // The browser's own retry would reuse the spent ticket and get 401: retry with a new one.
    source.onerror = reconnect;
  }

  connect();
  return () => {
    stopped = true;
    clearTimeout(retry);
    source?.close();
  };
}

/** Calls onEvent with the data of each `type` event while the component is mounted. */
export function useProgressEvents(type: string, onEvent: (data: unknown) => void): void {
  const handle = useEffectEvent(onEvent);
  useEffect(() => subscribe(type, handle), [type]);
}
