let csrf = "";

export function setCsrf(token: string) {
  csrf = token;
}

export function getCsrf() {
  return csrf;
}

export async function api(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") headers.set("x-csrf-token", csrf);
  headers.set("content-type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  const data = await res.json();
  if (!res.ok) throw data;
  return data;
}
