import { useCallback, useEffect, useState } from "react";
import { closeRviz, getControlOptions, getNavigationReadiness, getStackStatus, openRviz, prepareNavigation, saveMap, startStack, stopStack } from "./api";
import { createRefreshGate } from "./refreshGate";
import type { ControlOptions, MapArtifact, NavigationReadiness, StackRequest, StackStatus } from "./types";

export function useControlCenter() {
  const [options, setOptions] = useState<ControlOptions | null>(null);
  const [stack, setStack] = useState<StackStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [navigationReadiness, setNavigationReadiness] = useState<NavigationReadiness | null>(null);

  const [refreshGate] = useState(createRefreshGate);

  const refresh = useCallback(() => refreshGate.run(async (isCurrent) => {
    try {
      const [nextOptions, nextStack] = await Promise.all([getControlOptions(), getStackStatus()]);
      if (!isCurrent()) return;
      setOptions(nextOptions);
      setStack(nextStack);
      if (nextStack.state === "running" && nextStack.mode === "navigation") {
        const readiness = await getNavigationReadiness();
        if (!isCurrent()) return;
        setNavigationReadiness(readiness);
      } else {
        setNavigationReadiness(null);
      }
      setError(null);
    } catch (err) {
      if (isCurrent()) setError(err instanceof Error ? err.message : "Control center request failed");
    }
  }), [refreshGate]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => {
      window.clearInterval(timer);
      refreshGate.invalidate();
    };
  }, [refresh, refreshGate]);

  const start = useCallback(async (request: StackRequest) => {
    const resumeRefresh = refreshGate.suspend();
    setBusy(true);
    try {
      const next = await startStack(request);
      setStack(next);
      if (next.state === "running" && next.mode === "navigation") {
        setNavigationReadiness(await getNavigationReadiness());
      } else {
        setNavigationReadiness(null);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stack start failed");
    } finally {
      resumeRefresh();
      setBusy(false);
      void refresh();
    }
  }, [refresh, refreshGate]);

  const stop = useCallback(async () => {
    const resumeRefresh = refreshGate.suspend();
    setBusy(true);
    try {
      setStack(await stopStack());
      setNavigationReadiness(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stack stop failed");
    } finally {
      resumeRefresh();
      setBusy(false);
      void refresh();
    }
  }, [refresh, refreshGate]);

  const launchRviz = useCallback(async () => {
    const resumeRefresh = refreshGate.suspend();
    setBusy(true);
    try {
      setStack(await openRviz());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "RViz launch failed");
    } finally {
      resumeRefresh();
      setBusy(false);
      void refresh();
    }
  }, [refresh, refreshGate]);

  const stopRviz = useCallback(async () => {
    const resumeRefresh = refreshGate.suspend();
    setBusy(true);
    try {
      setStack(await closeRviz());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "RViz close failed");
    } finally {
      resumeRefresh();
      setBusy(false);
      void refresh();
    }
  }, [refresh, refreshGate]);

  const saveCurrentMap = useCallback(async (name: string, overwrite = false): Promise<MapArtifact | null> => {
    const resumeRefresh = refreshGate.suspend();
    setBusy(true);
    try {
      const result = await saveMap(name, overwrite);
      setError(null);
      return result.map;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Map save failed");
      return null;
    } finally {
      resumeRefresh();
      setBusy(false);
      void refresh();
    }
  }, [refresh, refreshGate]);

  const retryNavigationReadiness = useCallback(async () => {
    const resumeRefresh = refreshGate.suspend();
    setBusy(true);
    try {
      setNavigationReadiness(await prepareNavigation());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Navigation preparation failed");
    } finally {
      resumeRefresh();
      setBusy(false);
      void refresh();
    }
  }, [refresh, refreshGate]);

  return { options, stack, navigationReadiness, error, busy, start, stop, launchRviz, stopRviz, saveCurrentMap, retryNavigationReadiness, refresh };
}
