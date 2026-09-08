import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nirikshan — AI-Powered SRE & Incident Response",
  description:
    "Nirikshan correlates telemetry, detects incidents, runs evidence-based AI investigations and gates safe remediation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
