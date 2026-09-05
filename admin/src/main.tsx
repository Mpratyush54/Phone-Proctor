import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, setCsrf } from "./api/client";
import "./styles.css";
import { Login } from "./pages/Login";
import { Exams } from "./pages/Exams";
import { Questions } from "./pages/Questions";
import { ExamSetup } from "./pages/ExamSetup";
import { CommandCenter } from "./pages/CommandCenter";
import { Review } from "./pages/Review";
import { Appeals } from "./pages/Appeals";
import { PlatformHealth } from "./pages/PlatformHealth";
import { StudentDrawer } from "./components/StudentDrawer";

const qc = new QueryClient();

type Me = { user_id: string; org_id: string; roles: string[]; permissions: string[]; csrf: string } | null | undefined;

const MeCtx = React.createContext<Me>(undefined);

function useMe() {
  return React.useContext(MeCtx);
}

function useMeLoader() {
  const [me, setMe] = React.useState<Me>(undefined);
  React.useEffect(() => {
    api("/api/v1/me")
      .then((m) => {
        setCsrf(m.csrf);
        setMe(m);
      })
      .catch(() => setMe(null));
  }, []);
  return me;
}

function Guard({ children, perm }: { children: React.ReactNode; perm?: string }) {
  const me = useMe();
  if (me === undefined) return <main className="content"><p className="muted">Loading session…</p></main>;
  if (me === null) return <Navigate to="/login" replace />;
  if (perm && !me.permissions.includes(perm) && !me.permissions.includes("platform.ops")) {
    return <main className="content">Missing permission {perm}</main>;
  }
  return <>{children}</>;
}

function Nav() {
  const loc = useLocation();
  const me = useMe();
  const links = [
    ["/exams", "Exams"],
    ["/banks", "Questions"],
    ["/review", "Review"],
    ["/appeals", "Appeals"],
    ["/platform", "Platform"],
  ] as const;
  async function logout() {
    await api("/api/v1/auth/logout", { method: "POST", body: "{}" }).catch(() => undefined);
    window.location.href = "/login";
  }
  return (
    <nav className="sidebar">
      <div className="brand">Phone<span>-</span>Proctor</div>
      {links.map(([to, label]) => (
        <Link key={to} className={`navlink${loc.pathname.startsWith(to) ? " active" : ""}`} to={to}>
          {label}
        </Link>
      ))}
      <div className="sidefoot">
        {me && typeof me === "object" ? (
          <>
            <div style={{ marginBottom: 8 }}>{me.roles.join(", ")}</div>
            <button onClick={logout}>Log out</button>
          </>
        ) : (
          <Link className="navlink" to="/login">Login</Link>
        )}
      </div>
    </nav>
  );
}

function Shell() {
  const me = useMeLoader();
  return (
    <MeCtx.Provider value={me}>
      <div className="shell">
        <Nav />
        <div className="content">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/exams" element={<Guard perm="exam.read"><Exams /></Guard>} />
            <Route path="/banks" element={<Guard perm="exam.read"><Questions /></Guard>} />
            <Route path="/exams/:id/setup" element={<Guard perm="exam.read"><ExamSetup /></Guard>} />
            <Route path="/exams/:id" element={<Guard perm="exam.read"><CommandCenter /></Guard>} />
            <Route path="/sessions/:id" element={<Guard perm="session.read"><StudentDrawer /></Guard>} />
            <Route path="/review" element={<Guard perm="review.annotate"><Review /></Guard>} />
            <Route path="/appeals" element={<Guard perm="appeal.decide"><Appeals /></Guard>} />
            <Route path="/platform" element={<Guard perm="platform.ops"><PlatformHealth /></Guard>} />
            <Route path="/" element={<Navigate to="/exams" replace />} />
          </Routes>
        </div>
      </div>
    </MeCtx.Provider>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={qc}>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </QueryClientProvider>,
);
