import { useMutation } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { api } from "../api/client";
import { Brand, Feedback } from "../components/ui";

export function Login({ onSignIn }: { onSignIn: () => Promise<void> }) {
  const login = useMutation({
    mutationFn: async () => {
      await api("/api/v1/auth/dev-login", { method: "POST", body: "{}" });
      await onSignIn();
    },
  });
  return <main className="auth-shell">
    <Brand />
    <div className="login-card">
      <section className="login-form">
        <h1>Sign in to Phone-Proctor</h1>
        <p>Staff access for this development environment.</p>
        <button className="primary" onClick={() => login.mutate()} disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Continue to development workspace"} <ArrowRight size={16} />
        </button>
        <Feedback error={login.error} />
      </section>
      <section className="login-aside">
        <h2>Welcome to your exam workspace.</h2>
        <p>Set up exams, enroll candidates, and monitor their sessions from one place.</p>
        <p>Review candidate activity and follow command receipts as agents respond.</p>
      </section>
    </div>
  </main>;
}
