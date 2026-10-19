import { useEffect } from "react";
import { AccountProvider, useAccount } from "./lib/account";
import { ToastProvider } from "./lib/hooks";
import { Redirect, Router, Routes, useRouter, type RouteDef } from "./lib/router";
import { Layout } from "./components/shell/Shell";
import { AuthModal } from "./components/AuthModal";
import { Spinner } from "./components/ui";
import { Home } from "./pages/public/Home";
import { Pricing } from "./pages/public/Pricing";
import { Disclaimer, Docs, Faq, Methodology, Trust } from "./pages/public/Static";
import { AcceptInvite, ForgotPassword, ResetPassword } from "./pages/public/Auth";
import { AppArea } from "./pages/app/AppArea";

const PUBLIC: RouteDef[] = [
  { path: "/", render: () => <Home /> },
  { path: "/pricing", render: () => <Pricing /> },
  { path: "/methodology", render: () => <Methodology /> },
  { path: "/trust", render: () => <Trust /> },
  { path: "/faq", render: () => <Faq /> },
  { path: "/disclaimer", render: () => <Disclaimer /> },
  { path: "/docs", render: () => <Docs /> },
  { path: "/forgot-password", render: () => <ForgotPassword /> },
  { path: "/reset-password", render: () => <ResetPassword /> },
  { path: "/invite", render: () => <AcceptInvite /> },
  { path: "/login", render: () => <LoginRoute /> },
  { path: "/signup", render: () => <LoginRoute signup /> },
];

function LoginRoute({ signup }: { signup?: boolean }) {
  const { openAuth, me, loading } = useAccount();
  useEffect(() => { if (!loading && !me) openAuth(signup ? "signup" : "login"); }, [loading, me, signup, openAuth]);
  return me ? <Redirect to="/app" /> : <Home />;
}

function Pages() {
  const { path } = useRouter();
  const { loading } = useAccount();
  useEffect(() => { document.title = "AIDAP — AI Data Assurance Platform"; }, [path]);
  if (path === "/app" || path.startsWith("/app/")) return loading ? <Spinner /> : <Layout><AppArea /></Layout>;
  return (
    <Layout>
      <Routes routes={PUBLIC} fallback={<div className="wrap"><div className="empty"><b>Page not found</b>That page doesn’t exist.</div></div>} />
    </Layout>
  );
}

export function App() {
  return (
    <ToastProvider>
      <Router>
        <AccountProvider>
          <Pages />
          <AuthModal />
        </AccountProvider>
      </Router>
    </ToastProvider>
  );
}
