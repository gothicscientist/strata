"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, api, clearGuest, ensureToken, readGuest, setExternalTokenSource } from "@/lib/api";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";
import type { Health } from "@/lib/types";

export type SessionState =
  | { status: "connecting" }
  | { status: "guest"; ownerId: string; expiresAt: string }
  | { status: "signed-in"; email: string | null }
  | { status: "offline"; message: string };

interface SessionCtx {
  session: SessionState;
  health: Health | null;
  supabase: boolean;
  signInWithEmail: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
  retry: () => void;
}

const Ctx = createContext<SessionCtx | null>(null);

export function useSession(): SessionCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used inside <SessionProvider>");
  return v;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionState>({ status: "connecting" });
  const [health, setHealth] = useState<Health | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | undefined;

    async function start() {
      let email: string | null | undefined;
      const sb = getSupabase();
      if (sb) {
        const client = await sb;
        setExternalTokenSource(async () => {
          const { data } = await client.auth.getSession();
          return data.session?.access_token ?? null;
        });
        const { data } = await client.auth.getSession();
        email = data.session ? (data.session.user.email ?? null) : undefined;
        const sub = client.auth.onAuthStateChange((_e, s) => {
          if (cancelled) return;
          if (s) setSession({ status: "signed-in", email: s.user.email ?? null });
        });
        unsubscribe = () => sub.data.subscription.unsubscribe();
      }

      try {
        const h = await api.health();
        if (cancelled) return;
        setHealth(h);
        if (email !== undefined) {
          setSession({ status: "signed-in", email });
          return;
        }
        // First visit (or expired token): create a guest workspace.
        await ensureToken();
        const g = readGuest();
        if (!cancelled && g) setSession({ status: "guest", ownerId: g.owner_id, expiresAt: g.expires_at });
      } catch (e) {
        if (cancelled) return;
        const message =
          e instanceof ApiError
            ? e.unreachable
              ? "The Strata API is not reachable."
              : e.message
            : "The Strata API is not reachable.";
        setSession({ status: "offline", message });
      }
    }
    void start();
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [attempt]);

  const signInWithEmail = useCallback(async (email: string) => {
    const sb = getSupabase();
    if (!sb) throw new Error("Email sign-in is not configured for this deployment.");
    const client = await sb;
    const { error } = await client.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/workspace/` },
    });
    if (error) throw new Error(error.message);
  }, []);

  const signOut = useCallback(async () => {
    const sb = getSupabase();
    if (sb) await (await sb).auth.signOut();
    clearGuest();
    setSession({ status: "connecting" });
    setAttempt((a) => a + 1);
  }, []);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  const value = useMemo(
    () => ({ session, health, supabase: supabaseConfigured, signInWithEmail, signOut, retry }),
    [session, health, signInWithEmail, signOut, retry],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
