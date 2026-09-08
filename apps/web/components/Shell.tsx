"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { clearSession, getUser, Me } from "@/lib/api";
import { useLiveEvents } from "@/lib/hooks";

const NAV: { href: string; label: string; group?: string }[] = [
  { href: "/", label: "Overview" },
  { href: "/services", label: "Services" },
  { href: "/service-map", label: "Service Map" },
  { href: "/incidents", label: "Incidents" },
  { href: "/alerts", label: "Alerts" },
  { href: "/logs", label: "Logs" },
  { href: "/metrics", label: "Metrics" },
  { href: "/traces", label: "Traces" },
  { href: "/deployments", label: "Deployments" },
  { href: "/investigations", label: "AI Investigations" },
  { href: "/remediations", label: "Remediations" },
  { href: "/history", label: "Incident History" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<Me | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      router.replace("/login");
      return;
    }
    setUser(u);
  }, [router]);

  useLiveEvents((e) => {
    const label =
      e.event === "INCIDENT_CREATED"
        ? `New incident ${e.incident_ref} on ${e.service}`
        : e.event === "REMEDIATION_PROPOSED"
          ? `Remediation ${e.remediation_ref} proposed`
          : e.event === "INVESTIGATION_COMPLETED"
            ? `Investigation complete for ${e.incident_ref}`
            : null;
    if (label) {
      setToast(label);
      setTimeout(() => setToast(null), 6000);
    }
  });

  if (!user) return <div className="p-8 text-muted">Loading…</div>;

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-border bg-panel">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="h-6 w-6 rounded bg-accent/20 text-center text-accent">◉</div>
          <div>
            <div className="text-sm font-bold tracking-wide">NIRIKSHAN</div>
            <div className="text-[10px] text-muted">SRE &amp; Incident Response</div>
          </div>
        </div>
        <nav className="px-2 pb-4">
          {NAV.map((n) => {
            const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`block rounded-md px-3 py-2 text-sm ${
                  active ? "bg-accent/15 text-accent" : "text-muted hover:bg-panel2 hover:text-text"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-panel px-6 py-3">
          <div className="text-sm text-muted">
            {NAV.find((n) => (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)))?.label ||
              "Nirikshan"}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="pill border-border text-muted">{user.role}</span>
            <span className="text-muted">{user.email}</span>
            <button
              className="btn"
              onClick={() => {
                clearSession();
                router.replace("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 p-6">{children}</main>
      </div>

      {toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-accent/50 bg-panel2 px-4 py-2 text-sm text-accent shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}
