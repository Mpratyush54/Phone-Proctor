import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { api, setCsrf } from "./api/client";
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

function useMe() {
  // undefined = still loading, null = unauthenticated, object = session
  const [me, setMe] = React.useState<Record<string, unknown> | null | undefined>(undefined);
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
  if (me === undefined) return <main>Loading session…</main>;
  if (me === null) return <Navigate to="/login" replace />;
  if (perm && Array.isArray(me.permissions) && !me.permissions.includes(perm) && !me.permissions.includes("platform.ops")) {
    return <main>Missing permission {perm}</main>;
  }
  return <>{children}</>;
}

function Shell() {
  return (
    <>
      <header>
        <b>Phone-Proctor</b>
        <Link to="/exams">Exams</Link>
        <Link to="/banks">Questions</Link>
        <Link to="/review">Review</Link>
        <Link to="/appeals">Appeals</Link>
        <Link to="/platform">Platform</Link>
        <Link to="/login">Login</Link>
      </header>
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
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={qc}>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </QueryClientProvider>,
);
