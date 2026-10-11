import { useEffect, useState } from "react";

export type StreamStatus = "connecting" | "live" | "reconnecting" | "expired" | "closed";

type State<T> = { url: string | null; data: T | null; status: StreamStatus };

/** Subscribes to one of the backend's SSE streams (docs/API.md, "Live streams").
 * The server sends a full snapshot on every (re)connect, so the latest frame is always the
 * truth; EventSource reconnects by itself after network blips (server sends `retry:`). */
export function useEventStream<T>(url: string | null, eventName: string) {
  const [state, setState] = useState<State<T>>({ url, data: null, status: "connecting" });

  useEffect(() => {
    if (!url) return;
    const source = new EventSource(url);
    const update = (patch: Partial<State<T>>) =>
      setState((prev) => ({ ...(prev.url === url ? prev : { data: null, status: "connecting" }), ...patch, url }));
    const onFrame = (event: MessageEvent<string>) =>
      update({ data: JSON.parse(event.data) as T, status: "live" });
    const onExpired = () => {
      update({ status: "expired" });
      source.close();
    };
    source.addEventListener(eventName, onFrame as EventListener);
    source.addEventListener("session_expired", onExpired);
    source.onopen = () => update({ status: "live" });
    source.onerror = () =>
      // CLOSED = the server refused (e.g. 401/404): EventSource will not retry by itself.
      update({ status: source.readyState === EventSource.CLOSED ? "closed" : "reconnecting" });
    return () => {
      source.removeEventListener(eventName, onFrame as EventListener);
      source.removeEventListener("session_expired", onExpired);
      source.close();
    };
  }, [url, eventName]);

  // State from a previous URL never leaks into the new one: until the new stream speaks,
  // we are "connecting" with no data.
  if (state.url !== url) return { data: null as T | null, status: "connecting" as StreamStatus };
  return { data: state.data, status: state.status };
}
