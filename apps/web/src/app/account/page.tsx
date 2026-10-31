"use client";

import { useState } from "react";
import { relativeExpiry } from "@/lib/format";
import { useSession } from "@/components/SessionProvider";
import { Caveat, ErrorNote, PageHeader, Section } from "@/components/typography";

export default function AccountPage() {
  const { session, supabase, signInWithEmail, signOut } = useSession();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  return (
    <>
      <PageHeader kicker="Account" title="Your workspace" />
      <Section n={1} title="Current session">
        <p className="measure text-small">
          {session.status === "guest" && (
            <>
              You are using a guest workspace, which {relativeExpiry(session.expiresAt)}. Its datasets
              and analyses are deleted when it expires.
            </>
          )}
          {session.status === "signed-in" && <>You are signed in{session.email ? ` as ${session.email}` : ""}.</>}
          {session.status === "connecting" && <>Connecting to the API&hellip;</>}
          {session.status === "offline" && <>{session.message}</>}
        </p>
        {session.status === "guest" || session.status === "signed-in" ? (
          <button type="button" className="btn btn-quiet mt-4" onClick={() => void signOut()}>
            {session.status === "guest" ? "Discard guest workspace and start a new one" : "Sign out"}
          </button>
        ) : null}
      </Section>

      <Section n={2} title="Sign in by email">
        {!supabase ? (
          <p className="measure text-small text-ink-2">
            This deployment runs in guest mode only. Email sign-in becomes available when the
            operator sets <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
            <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code>.
          </p>
        ) : sent ? (
          <p className="measure text-small">
            A sign-in link has been sent to {email}. Open it on this device to continue.
          </p>
        ) : (
          <form
            className="max-w-[24rem]"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError(null);
              try {
                await signInWithEmail(email);
                setSent(true);
              } catch (err) {
                setError(err);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="block">
              <span className="label">Email address</span>
              <input className="field" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <button type="submit" className="btn mt-4" disabled={busy || !email}>
              {busy ? "Sending…" : "Send sign-in link"}
            </button>
            {error ? <ErrorNote error={error} /> : null}
          </form>
        )}
        <Caveat title="Guest work is not transferred">
          Datasets and analyses created as a guest stay in the guest workspace and expire with it.
        </Caveat>
      </Section>
    </>
  );
}
