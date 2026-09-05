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
    <div className="wrap">
      <div className="card">
        <h1>Candidate login</h1>
        <p className="muted">Enter the one-time code issued for your enrollment. Codes are single-candidate, limited-use, and expire.</p>
        <input
          className="code"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="A1B2C3D4E5F6"
        />
        <div className="toolbar">
          <button onClick={login} style={{ flex: 1 }}>Start exam</button>
        </div>
        {err && <pre className="err">{err}</pre>}
      </div>
    </div>
  );
}
