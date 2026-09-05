import React from "react";

export function Login() {
  const [err, setErr] = React.useState("");
  return (
    <div className="loginwrap">
      <div className="logincard">
        <h1>Staff login</h1>
        <p className="muted">Same-origin OIDC session. Access tokens are never stored in localStorage.</p>
        <button
          style={{ width: "100%", marginTop: 12 }}
          onClick={() => {
            window.location.href = "/api/v1/auth/login";
          }}
        >
          Continue with OIDC
        </button>
        {err && <pre className="dump err">{err}</pre>}
      </div>
    </div>
  );
}
