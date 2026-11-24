import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useMutation, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Activity, ClipboardList, Gavel, LayoutDashboard, LogOut, ScanEye, Search, ServerCog, ShieldCheck } from "lucide-react";
import { api, ApiError, setCsrf } from "./api/client";
import { StaffContext, usePermissions, type Staff } from "./auth";
import { Login } from "./pages/Login";
import { Exams } from "./pages/Exams";
import { ExamSetup } from "./pages/ExamSetup";
import { CommandCenter } from "./pages/CommandCenter";
import { Review } from "./pages/Review";
import { Appeals } from "./pages/Appeals";
import { PlatformHealth } from "./pages/PlatformHealth";
import { StudentDrawer } from "./components/StudentDrawer";
import { Brand, Failure, Feedback, State } from "./components/ui";
import "./styles.css";

const staffKey = ["staff"];
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const navigation = [
  { to: "/", name: "Overview", icon: LayoutDashboard, permission: "exam.read" },
  { to: "/exams", name: "Exams", icon: ClipboardList, permission: "exam.read" },
  { to: "/monitor", name: "Monitoring", icon: Activity, permission: "session.read" },
  { to: "/review", name: "Evidence review", icon: ScanEye, permission: "review.annotate" },
  { to: "/appeals", name: "Appeals", icon: Gavel, permission: "appeal.decide" },
  { to: "/platform", name: "Platform health", icon: ServerCog, permission: "platform.ops" },
];

function Guard({ children, permission }: { children: React.ReactNode; permission: string }) {
  const allowed = usePermissions();
  return allowed(permission) ? <>{children}</> : <main><State title="Access restricted" icon={ShieldCheck}><p>Your staff role does not allow access to this page.</p></State></main>;
}

function Shell({ staff, onSignOut }: { staff: Staff; onSignOut: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [search, setSearch] = React.useState("");
  const allowed = usePermissions();
  const logout = useMutation({ mutationFn: () => api("/api/v1/auth/logout", { method: "POST", body: "{}" }), onSuccess: onSignOut });
  const path = location.pathname;
  const isSession = path.startsWith("/sessions/");
  const isExamFeed = /^\/exams\/[^/]+\/?$/.test(path);
  const active = isSession || isExamFeed ? "/monitor"
    : navigation.find(({ to }) => path === to || path.startsWith(to + "/"))?.to;
  const section = isSession ? "Candidate session" : navigation.find(({ to }) => to === active)?.name ?? "Workspace";
  const SectionIcon = navigation.find(({ to }) => to === active)?.icon ?? LayoutDashboard;
  const role = staff.roles?.[0]?.replace(/_/g, " ") ?? "Staff";
  return <div className="workspace">
    <aside className="sidebar">
      <div className="sidebar-brand"><Brand /></div>
      {allowed("exam.read") && <form className="sidebar-search search-box" role="search" aria-label="Workspace search" onSubmit={(event) => {
        event.preventDefault();
        const query = search.trim();
        navigate(query ? `/exams?q=${encodeURIComponent(query)}` : "/exams");
        setSearch("");
      }}>
        <Search size={16} aria-hidden="true" />
        <input aria-label="Find an exam" placeholder="Find an exam" value={search} onChange={(event) => setSearch(event.target.value)} />
      </form>}
      <nav aria-label="Workspace navigation">
        {navigation.filter((entry) => allowed(entry.permission)).map(({ to, name, icon: Icon }) =>
          <React.Fragment key={to}>
            {to === "/review" && <div className="nav-label">Review &amp; operations</div>}
            <Link to={to} className={active === to ? "active" : undefined} aria-current={active === to ? "page" : undefined}><Icon size={16} strokeWidth={1.7} aria-hidden="true" /><span>{name}</span></Link>
          </React.Fragment>)}
      </nav>
      <div className="sidebar-footer"><div className="profile"><span className="avatar"><ShieldCheck size={16} /></span><div><strong>Staff session</strong><small>{role}</small></div></div>
        <button className="icon-button" aria-label="Sign out" title="Sign out" onClick={() => logout.mutate()} disabled={logout.isPending}><LogOut size={17} /></button>
      </div>
      <Feedback error={logout.error} />
    </aside>
    <div className="workspace-body">
      <header className="topbar"><span className="topbar-section"><SectionIcon size={16} strokeWidth={1.7} /> <b>{section}</b></span><span className="topbar-label">Staff console</span></header>
      <Routes>
        <Route path="/" element={<Guard permission="exam.read"><Exams mode="overview" /></Guard>} />
        <Route path="/exams" element={<Guard permission="exam.read"><Exams mode="exams" /></Guard>} />
        <Route path="/monitor" element={<Guard permission="session.read"><Exams mode="monitor" /></Guard>} />
        <Route path="/exams/:id/setup" element={<Guard permission="exam.read"><ExamSetup /></Guard>} />
        <Route path="/exams/:id" element={<Guard permission="session.read"><CommandCenter /></Guard>} />
        <Route path="/sessions/:id" element={<Guard permission="session.read"><StudentDrawer /></Guard>} />
        <Route path="/review" element={<Guard permission="review.annotate"><Review /></Guard>} />
        <Route path="/appeals" element={<Guard permission="appeal.decide"><Appeals /></Guard>} />
        <Route path="/platform" element={<Guard permission="platform.ops"><PlatformHealth /></Guard>} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<main><State title="Page not found"><p>Choose a page from the workspace navigation.</p></State></main>} />
      </Routes>
    </div>
  </div>;
}

function App() {
  const staff = useQuery({
    queryKey: staffKey,
    queryFn: async ({ signal }) => {
      try {
        const current = await api<Staff>("/api/v1/me", { signal });
        setCsrf(current.csrf);
        return current;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
  });
  const clearSession = React.useCallback(() => {
    setCsrf("");
    void qc.cancelQueries();
    qc.removeQueries({ predicate: (query) => query.queryKey[0] !== staffKey[0] });
    qc.setQueryData(staffKey, null);
  }, []);
  React.useEffect(() => {
    window.addEventListener("staff-session-expired", clearSession);
    return () => window.removeEventListener("staff-session-expired", clearSession);
  }, [clearSession]);
  if (staff.isPending) return <main className="auth-shell"><State title="Checking your staff session" kind="loading" /></main>;
  if (staff.isError) return <main className="auth-shell"><Failure title="The workspace is unavailable" error={staff.error} retry={() => void staff.refetch()} /></main>;
  if (!staff.data) return <Login onSignIn={async () => { await staff.refetch({ throwOnError: true }); }} />;
  return <StaffContext.Provider value={staff.data}><Shell staff={staff.data} onSignOut={clearSession} /></StaffContext.Provider>;
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={qc}><BrowserRouter><App /></BrowserRouter></QueryClientProvider>,
);
