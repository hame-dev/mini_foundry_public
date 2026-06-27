import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startPolling } from "@/lib/polling";

describe("startPolling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("polls until a terminal value and then stops", async () => {
    const values = [{ status: "running" }, { status: "running" }, { status: "done" }];
    let i = 0;
    const load = vi.fn(async () => values[Math.min(i++, values.length - 1)]);
    const onValue = vi.fn();

    startPolling({
      load,
      isTerminal: (v) => v.status === "done",
      onValue,
      minDelayMs: 1000,
    });

    // initial tick (delay 0) + two more polls
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(1000);
    const callsAtTerminal = load.mock.calls.length;

    // no further polling after terminal
    await vi.advanceTimersByTimeAsync(5000);
    expect(load.mock.calls.length).toBe(callsAtTerminal);
    expect(onValue).toHaveBeenLastCalledWith({ status: "done" });
  });

  it("cleanup cancels further polling", async () => {
    const load = vi.fn(async () => ({ status: "running" }));
    const stop = startPolling({ load, isTerminal: () => false, onValue: () => {}, minDelayMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    const calls = load.mock.calls.length;
    stop();
    await vi.advanceTimersByTimeAsync(10000);
    expect(load.mock.calls.length).toBe(calls);
  });
});
