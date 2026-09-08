"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@nirikshan.dev");
  const [password, setPassword] = useState("admin12345");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded bg-accent/20 text-center text-lg text-accent">◉</div>
          <div>
            <div className="font-bold tracking-wide">NIRIKSHAN</div>
            <div className="text-xs text-muted">SRE &amp; Incident Response Platform</div>
          </div>
        </div>
        <label className="block text-sm">
          <span className="text-muted">Email</span>
          <input className="input mt-1 w-full" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="text-muted">Password</span>
          <input
            type="password"
            className="input mt-1 w-full"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <div className="text-sm text-bad">{error}</div>}
        <button className="btn btn-primary w-full justify-center" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-xs text-muted">
          Demo users (after <code>demo/seed</code>): <code>engineer@nirikshan.dev</code>,{" "}
          <code>incident_commander@nirikshan.dev</code>, <code>admin@nirikshan.dev</code> — password{" "}
          <code>&lt;role&gt;12345</code>.
        </p>
      </form>
    </div>
  );
}
