import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { FakeEventSource, installEventSource } from "./test/fakes";
import { useEventStream } from "./useEventStream";

describe("useEventStream", () => {
  beforeEach(installEventSource);

  it("applies_snapshots_and_reconnects", () => {
    const { result } = renderHook(() => useEventStream<{ n: number }>("/api/x/stream", "stats"));
    const source = FakeEventSource.latest("/api/x/stream");
    expect(result.current).toEqual({ data: null, status: "connecting" });

    source.emit("stats", { n: 1 });
    expect(result.current).toEqual({ data: { n: 1 }, status: "live" });

    source.fail(); // network blip: browser retries by itself
    expect(result.current.status).toBe("reconnecting");
    expect(result.current.data).toEqual({ n: 1 }); // last known numbers stay visible

    source.emit("stats", { n: 5 }); // fresh snapshot after reconnect
    expect(result.current).toEqual({ data: { n: 5 }, status: "live" });
  });

  it("reports_closed_when_server_refuses", () => {
    const { result } = renderHook(() => useEventStream("/api/x/stream", "stats"));
    FakeEventSource.latest("/api/x/stream").fail(true);
    expect(result.current.status).toBe("closed");
  });

  it("stops_on_session_expired", () => {
    const { result } = renderHook(() => useEventStream("/api/x/stream", "stats"));
    const source = FakeEventSource.latest("/api/x/stream");
    source.emit("session_expired", {});
    expect(result.current.status).toBe("expired");
    expect(source.readyState).toBe(FakeEventSource.CLOSED);
  });

  it("closes_on_unmount_and_ignores_other_events", () => {
    const { result, unmount } = renderHook(() => useEventStream("/api/x/stream", "stats"));
    const source = FakeEventSource.latest("/api/x/stream");
    source.emit("availability", { n: 9 });
    expect(result.current.data).toBeNull();
    unmount();
    expect(source.readyState).toBe(FakeEventSource.CLOSED);
  });

  it("does_not_connect_without_url", () => {
    renderHook(() => useEventStream(null, "stats"));
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
