"use client";

import Link from "next/link";
import { ReactNode } from "react";

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`card ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between">
          {title && <h3 className="text-sm font-semibold text-text">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "bad" | "warn" | "ok";
}) {
  const toneCls =
    tone === "bad"
      ? "text-bad"
      : tone === "warn"
        ? "text-warn"
        : tone === "ok"
          ? "text-ok"
          : "text-text";
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneCls}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-panel2">
          <tr>
            {head.map((h) => (
              <th key={h} className="th">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-muted">{children}</div>;
}

export function Loading() {
  return <div className="py-10 text-center text-sm text-muted">Loading…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-bad/50 bg-bad/10 px-3 py-2 text-sm text-bad">
      {message}
    </div>
  );
}

export function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="max-h-[420px] overflow-auto rounded-md border border-border bg-bg p-3 text-xs text-muted">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function KV({ k, children }: { k: string; children: ReactNode }) {
  return (
    <>
      <div className="text-muted">{k}</div>
      <div>{children}</div>
    </>
  );
}

export function LinkPill({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="pill border-border text-accent hover:border-accent">
      {children}
    </Link>
  );
}

export function ConfidenceBar({ value }: { value: number | null | undefined }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const tone = v >= 0.8 ? "bg-ok" : v >= 0.5 ? "bg-warn" : "bg-bad";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-border">
        <div className={`h-full ${tone}`} style={{ width: `${v * 100}%` }} />
      </div>
      <span className="text-xs text-muted">{value == null ? "—" : v.toFixed(2)}</span>
    </div>
  );
}
