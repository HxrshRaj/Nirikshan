"use client";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

const TOKEN_KEY = "nirikshan.access";
const REFRESH_KEY = "nirikshan.refresh";
const USER_KEY = "nirikshan.user";

export type Role = "VIEWER" | "ENGINEER" | "INCIDENT_COMMANDER" | "ADMIN";
export interface Me {
  id: string;
  email: string;
  full_name: string;
  role: Role;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}
export function getUser(): Me | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as Me) : null;
}
export function setSession(access: string, refresh: string, user: Me) {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function raw<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined" && !path.includes("/auth/")) {
      clearSession();
      // hard nav is intentional here: clear all client state on forced logout
      window.location.assign("/login");
    }
    throw new ApiError(
      res.status,
      data?.code || "error",
      data?.message || res.statusText,
      data?.details
    );
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => raw<T>("GET", p),
  post: <T>(p: string, b?: unknown) => raw<T>("POST", p, b ?? {}),
  patch: <T>(p: string, b?: unknown) => raw<T>("PATCH", p, b ?? {}),
};

export async function login(email: string, password: string): Promise<Me> {
  const tok = await raw<{ access_token: string; refresh_token: string }>(
    "POST",
    "/api/auth/login",
    { email, password }
  );
  localStorage.setItem(TOKEN_KEY, tok.access_token);
  localStorage.setItem(REFRESH_KEY, tok.refresh_token);
  const me = await raw<Me>("GET", "/api/auth/me");
  localStorage.setItem(USER_KEY, JSON.stringify(me));
  return me;
}

export function eventStreamUrl(): string {
  return `${BASE}/api/stream`;
}

export const roleRank: Record<Role, number> = {
  VIEWER: 0,
  ENGINEER: 1,
  INCIDENT_COMMANDER: 2,
  ADMIN: 3,
};
export function atLeast(role: Role | undefined, min: Role): boolean {
  if (!role) return false;
  return roleRank[role] >= roleRank[min];
}
