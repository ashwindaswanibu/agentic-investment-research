"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { message, request } from "./api";

export function useResource<T>(
  path: string | null,
  parse: (value: unknown) => T,
  pollMs = 0,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (!path) {
      setLoading(false);
      return;
    }
    controller.current?.abort();
    const active = new AbortController();
    controller.current = active;
    try {
      const result = await request(path, parse, { signal: active.signal });
      if (!active.signal.aborted) {
        setData(result);
        setError(null);
        setUpdatedAt(new Date().toISOString());
      }
    } catch (e) {
      if (!active.signal.aborted) setError(message(e));
    } finally {
      if (!active.signal.aborted) setLoading(false);
    }
  }, [path, parse]);
  useEffect(() => {
    setData(null);
    setError(null);
    setLoading(true);
    setUpdatedAt(null);
    void refresh();
    const timer =
      pollMs > 0
        ? setInterval(() => {
            if (document.visibilityState === "visible") void refresh();
          }, pollMs)
        : undefined;
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const onSession = () => {
      setData(null);
      setError(null);
      setLoading(true);
      void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("research-session-changed", onSession);
    return () => {
      controller.current?.abort();
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("research-session-changed", onSession);
    };
  }, [refresh, pollMs]);
  return { data, error, loading, updatedAt, refresh };
}
