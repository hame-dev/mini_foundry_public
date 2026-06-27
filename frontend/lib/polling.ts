export type PollOptions<T> = {
  load: () => Promise<T>;
  isTerminal: (value: T) => boolean;
  onValue: (value: T) => void;
  minDelayMs?: number;
  maxDelayMs?: number;
};

export function startPolling<T>({
  load,
  isTerminal,
  onValue,
  minDelayMs = 1000,
  maxDelayMs = 15000,
}: PollOptions<T>) {
  let stopped = false;
  let delay = minDelayMs;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function tick() {
    if (stopped) return;
    try {
      const value = await load();
      onValue(value);
      if (isTerminal(value)) return;
      delay = minDelayMs;
    } catch {
      delay = Math.min(delay * 2, maxDelayMs);
    }
    timer = setTimeout(tick, delay);
  }

  timer = setTimeout(tick, 0);
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}
