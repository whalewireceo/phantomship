import { useEffect, useRef, useState } from "react";

/**
 * usePoll: runs an async fetcher on an interval and exposes its latest value.
 * Skips overlapping calls; pauses when the tab is hidden to save bandwidth.
 */
export function usePoll<T>(
  fetcher: () => Promise<T>,
  intervalMs: number
): { data: T | null; error: Error | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const inFlight = useRef(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let mounted = true;

    const tick = async () => {
      if (document.hidden || inFlight.current) return;
      inFlight.current = true;
      try {
        const next = await fetcherRef.current();
        if (mounted) {
          setData(next);
          setError(null);
        }
      } catch (e) {
        if (mounted) setError(e as Error);
      } finally {
        inFlight.current = false;
        if (mounted) setLoading(false);
      }
    };

    tick();
    const id = window.setInterval(tick, intervalMs);
    const visHandler = () => {
      if (!document.hidden) tick();
    };
    document.addEventListener("visibilitychange", visHandler);

    return () => {
      mounted = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", visHandler);
    };
  }, [intervalMs]);

  return { data, error, loading };
}
