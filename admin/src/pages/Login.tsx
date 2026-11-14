import React from "react";
import { api, setCsrf } from "../api/client";

export function Login() {
  const [err, setErr] = React.useState("");
  return (
    <main>
      <h1>Staff login</h1>
      <p>Same-origin OIDC session. Access tokens are never stored in localStorage.</p>
      <button
        onClick={async () => {
          try {
            const cb = await api("/api/v1/auth/dev-login", { method: "POST", body: "{}" });
            setCsrf(cb.csrf);
            window.location.href = "/exams";
          } catch (e) {
            setErr(JSON.stringify(e));
          }
        }}
      >
        Continue with OIDC
      </button>
      <pre>{err}</pre>
    </main>
  );
}
