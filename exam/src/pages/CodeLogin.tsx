import React from "react";
import { useNavigate } from "react-router-dom";
import { api, setCsrf } from "../api/client";

export function CodeLogin() {
  const nav = useNavigate();
  const [code, setCode] = React.useState("");
  const [err, setErr] = React.useState("");
  async function login() {
    setErr("");
    try {
      const res = await api("/api/v1/candidate/login", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setCsrf(res.csrf);
      nav("/exam", { state: { exam: res.exam } });
    } catch (e) {
      setErr(JSON.stringify(e));
    }
  }
  return (
    <main style={{ maxWidth: 480, margin: "4rem auto", fontFamily: "system-ui" }}>
      <h1>Candidate login</h1>
      <p>Enter the one-time code issued for your enrollment. Codes are single-candidate, limited-use, and expire.</p>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        placeholder="e.g. A1B2C3D4E5F6"
        style={{ width: "100%", padding: 10, fontSize: 18, letterSpacing: 2 }}
      />
      <button onClick={login} style={{ marginTop: 12, padding: "10px 24px", fontSize: 16 }}>
        Start exam
      </button>
      {err && <pre style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{err}</pre>}
    </main>
  );
}
