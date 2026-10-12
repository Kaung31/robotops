/** Keep polling single-flight and discard responses superseded by a control action. */
export function createRefreshGate() {
  let generation = 0;
  let paused = 0;
  let pending: Promise<void> | null = null;

  return {
    invalidate() { generation += 1; },
    suspend() {
      generation += 1;
      paused += 1;
      return () => { paused -= 1; generation += 1; };
    },
    run(work: (isCurrent: () => boolean) => Promise<void>): Promise<void> {
      if (paused) return Promise.resolve();
      if (pending) return pending;
      const started = generation;
      const isCurrent = () => generation === started && paused === 0;
      pending = Promise.resolve()
        .then(() => { if (isCurrent()) return work(isCurrent); })
        .finally(() => { pending = null; });
      return pending;
    },
  };
}
