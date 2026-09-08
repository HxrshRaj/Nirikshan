"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, eventStreamUrl, getToken } from "./api";

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api.get<T>(path));
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
     
  }, [path]);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  return { data, error, loading, reload, setData };
}

/** Poll an endpoint on an interval (used where SSE is not wired for a view). */
export function usePolling<T>(path: string | null, ms = 5000) {
  const { data, error, loading, reload } = useApi<T>(path);
  useEffect(() => {
    if (!path) return;
    const id = setInterval(reload, ms);
    return () => clearInterval(id);
  }, [path, ms, reload]);
  return { data, error, loading, reload };
}

export interface LiveEvent {
  event: string;
  [k: string]: unknown;
}

/** Subscribe to the backend SSE stream; calls onEvent for every message. */
export function useLiveEvents(onEvent: (e: LiveEvent) => void) {
  const cb = useRef(onEvent);
  useEffect(() => {
    cb.current = onEvent;
  }, [onEvent]);
  useEffect(() => {
    if (typeof window === "undefined" || !getToken()) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(eventStreamUrl());
      es.onmessage = (m) => {
        try {
          cb.current(JSON.parse(m.data));
        } catch {
          /* ignore keepalives */
        }
      };
      es.onerror = () => {
        /* browser auto-reconnects */
      };
    } catch {
      /* SSE unavailable - views still poll */
    }
    return () => es?.close();
  }, []);
}
