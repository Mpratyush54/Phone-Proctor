let csrf = "";

export function setCsrf(token: string) {
  csrf = token;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

export function describeError(error: unknown) {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") headers.set("x-csrf-token", csrf);
  if (init.body) headers.set("content-type", "application/json");
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new Error("Could not reach Phone-Proctor. Check your connection and try again.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (path !== "/api/v1/me" && path !== "/api/v1/auth/dev-login" && res.status === 401) {
      window.dispatchEvent(new Event("staff-session-expired"));
    }
    throw new ApiError(res.status, data?.message ?? data?.error?.message ?? (typeof data?.error === "string" ? data.error : undefined) ?? `Request failed (HTTP ${res.status}).`, data?.code ?? data?.error?.code);
  }
  if (data === null) throw new Error("The server returned an invalid response.");
  return data as T;
}
