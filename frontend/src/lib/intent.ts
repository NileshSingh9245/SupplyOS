"use client";

import { useState } from "react";
import axios from "axios";
import { api, apiError } from "./api";

export function createRequestIntent() {
  let current: { key: string; payload: string } | null = null;
  let active = false;
  return {
    begin(payload: unknown): string | null {
      if (active) return null;
      const serialized = JSON.stringify(payload);
      if (!current || current.payload !== serialized) {
        current = { key: crypto.randomUUID(), payload: serialized };
      }
      active = true;
      return current.key;
    },
    finish(error?: unknown) {
      active = false;
      const status = axios.isAxiosError(error) ? error.response?.status : undefined;
      // A timeout/network/5xx result may have committed; retry that intent, not a new payment.
      if (!error || (status !== undefined && status >= 400 && status < 500 && status !== 408)) {
        current = null;
      }
    },
    change() {
      if (!active) current = null;
    },
    get unresolved() { return current !== null && !active; },
  };
}

export function useIntentPost() {
  const [intent] = useState(createRequestIntent);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);

  async function post<T>(path: string, body: unknown): Promise<T | null> {
    const key = intent.begin(body);
    if (!key) return null;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<T>(path, body, { headers: { "X-Idempotency-Key": key } });
      intent.finish();
      setUnconfirmed(false);
      return data;
    } catch (failure) {
      intent.finish(failure);
      if (!axios.isCancel(failure)) {
        setError(apiError(failure));
        setUnconfirmed(intent.unresolved);
      }
      return null;
    } finally {
      setBusy(false);
    }
  }

  function payloadChanged() {
    intent.change();
    setError(null);
    setUnconfirmed(false);
  }

  return { post, busy, error, unconfirmed, payloadChanged };
}
