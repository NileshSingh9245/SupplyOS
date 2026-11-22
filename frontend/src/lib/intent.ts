"use client";

import { useState } from "react";
import axios from "axios";
import { api, apiError } from "./api";

export function createRequestIntent() {
  let current: { key: string; payload: string } | null = null;
  let active = false;
  let uncertain = false;
  return {
    begin(payload: unknown): string | null {
      if (active) return null;
      const serialized = JSON.stringify(payload);
      if (current && current.payload !== serialized) return null;
      if (!current) {
        current = { key: crypto.randomUUID(), payload: serialized };
      }
      active = true;
      return current.key;
    },
    finish(error?: unknown) {
      active = false;
      const status = axios.isAxiosError(error) ? error.response?.status : undefined;
      // A timeout/network/5xx result may have committed; retry that intent, not a new payment.
      if (!error || (!uncertain && status !== undefined && status >= 400 && status < 500 && status !== 408)) {
        current = null;
        uncertain = false;
      } else uncertain = true;
    },
    change() {
      return !active && current === null;
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
    let frozen: unknown;
    try { frozen = JSON.parse(JSON.stringify(body)); }
    catch { setError("The request could not be prepared. No request was sent."); return null; }
    const key = intent.begin({ path, body: frozen });
    if (!key) {
      if (intent.unresolved) setError("The original result is still unconfirmed. Retry its unchanged request before creating another intent.");
      return null;
    }
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<T>(path, frozen, { headers: { "X-Idempotency-Key": key } });
      intent.finish();
      setUnconfirmed(false);
      return data;
    } catch (failure) {
      intent.finish(failure);
      setError(axios.isCancel(failure) ? "The request was interrupted. Its result could not be confirmed." : apiError(failure));
      setUnconfirmed(intent.unresolved);
      return null;
    } finally {
      setBusy(false);
    }
  }

  function payloadChanged() {
    if (intent.change()) {
      setError(null);
      setUnconfirmed(false);
    }
  }

  return { post, busy, error, unconfirmed, payloadChanged };
}
