import { lazy, Suspense, useEffect, useEffectEvent, useState, type ChangeEvent, type ElementType } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, FlaskConical, ScrollText, Settings, Activity, Route as RouteIcon, DollarSign, Search, Sparkles } from 'lucide-react';

import { api, type PortfolioApp } from './api';
import { cn } from './utils';

const PortfolioCommandCenter = lazy(() => import('./pages/PortfolioCommandCenter'));
const FunnelDiagnostics = lazy(() => import('./pages/FunnelDiagnostics'));
const ExperimentCenter = lazy(() => import('./pages/ExperimentCenter'));
const ActionLog = lazy(() => import('./pages/ActionLog'));
const RevenueMonetization = lazy(() => import('./pages/RevenueMonetization'));
const ASOWorkspace = lazy(() => import('./pages/ASOWorkspace'));
const JourneyMap = lazy(() => import('./pages/JourneyMap'));
const SystemSettings = lazy(() => import('./pages/Settings'));
const AIChatPanel = lazy(() => import('./components/AIChatPanel'));

function RouteLoading() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-8" role="status">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-primary border-t-transparent" />
      <span className="animate-pulse font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">Loading workspace</span>
    </div>
  );
}

interface SidebarProps {
  aiOpen: boolean;
  onToggleAI: () => void;
}

function Sidebar({ aiOpen, onToggleAI }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [apps, setApps] = useState<PortfolioApp[]>([]);
  const [appsUnavailable, setAppsUnavailable] = useState(false);

  useEffect(() => {
    api.getPortfolio()
      .then(res => { if (res?.apps) setApps(res.apps); })
      .catch(() => setAppsUnavailable(true));
  }, []);

  const match = location.pathname.match(/\/app\/([^/]+)/);
  const currentApp = match ? decodeURIComponent(match[1]) : '';

  const handleAppChange = (e: ChangeEvent<HTMLSelectElement>) => {
    const newApp = e.target.value;
    if (!newApp) return;
    const parts = location.pathname.split('/');
    const encodedApp = encodeURIComponent(newApp);
    navigate(parts[1] === 'app' && parts[3] ? `/app/${encodedApp}/${parts[3]}` : `/app/${encodedApp}/funnel`);
  };

  const navItem = (path: string, label: string, Icon: ElementType) => {
    const isActive = location.pathname.startsWith(path);
    return (
      <Link
        to={path}
        className={cn(
          "flex items-center gap-3 px-4 py-2.5 rounded-r-full my-0.5 text-sm font-medium transition-colors border-l-2",
          isActive
            ? "bg-gradient-to-r from-accent-primary/20 to-transparent text-text-primary border-accent-primary"
            : "text-text-secondary hover:text-text-primary hover:bg-surface border-transparent"
        )}
      >
        <Icon className="w-4 h-4 shrink-0" />
        <span className="hidden lg:inline">{label}</span>
      </Link>
    );
  };

  return (
    <aside className="w-20 lg:w-64 border-r border-border-subtle bg-background-base/80 backdrop-blur-xl h-screen sticky top-0 flex flex-col pt-5 z-50 shrink-0 transition-[width]">
      {/* Logo */}
      <div className="px-5 mb-6 flex items-center gap-3">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-accent-primary to-accent-secondary flex items-center justify-center font-heading font-bold text-white text-sm shadow-[0_0_15px_rgba(139,92,246,0.4)]">
          K
        </div>
        <span className="hidden lg:inline font-heading font-bold tracking-wider text-lg text-text-primary">JMIP</span>
      </div>

      {/* App selector */}
      <div className="hidden lg:block px-5 mb-5">
        <select
          value={currentApp && apps.some(app => app.package_name === currentApp) ? currentApp : ''}
          onChange={handleAppChange}
          disabled={apps.length === 0}
          className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary outline-none focus:border-accent-primary font-mono"
        >
          <option value="">{appsUnavailable ? 'Apps unavailable' : 'Select an app'}</option>
          {apps.map(app => (
            <option key={app.package_name} value={app.package_name}>
              {app.display_name}
            </option>
          ))}
        </select>
      </div>

      {/* Nav */}
      <div className="flex-1 overflow-y-auto pr-3">
        <div className="mb-5">
          <div className="hidden lg:block px-5 mb-1.5 text-[10px] font-semibold tracking-widest text-text-muted uppercase">Portfolio</div>
          {navItem("/portfolio", "Command Center", LayoutDashboard)}
          {navItem("/experiments", "Experiment Center", FlaskConical)}
          {navItem("/actions", "Action Log", ScrollText)}
        </div>
        <div className="mb-5">
          <div className="hidden lg:block px-5 mb-1.5 text-[10px] font-semibold tracking-widest text-text-muted uppercase">App Views</div>
          {currentApp && navItem(`/app/${encodeURIComponent(currentApp)}/funnel`, "Funnel & Diagnostics", Activity)}
          {currentApp && navItem(`/app/${encodeURIComponent(currentApp)}/journey`, "Journey Map", RouteIcon)}
          {currentApp && navItem(`/app/${encodeURIComponent(currentApp)}/revenue`, "Revenue & Monetization", DollarSign)}
          {currentApp && navItem(`/app/${encodeURIComponent(currentApp)}/aso`, "ASO Workspace", Search)}
        </div>
      </div>

      {/* Bottom: AI toggle + Settings */}
      <div className="shrink-0 border-t border-border-subtle/50 pt-3 pb-4 pr-3">
        {/* AI Chat toggle — like Cursor's bottom bar */}
        <button
          onClick={onToggleAI}
          disabled={!currentApp}
          title={currentApp ? 'Toggle app AI chat' : 'Select an app to use AI chat'}
          className={cn(
            "flex items-center gap-2.5 w-full px-4 py-2.5 rounded-r-full text-sm font-medium transition-all border-l-2 mb-1 disabled:opacity-40 disabled:cursor-not-allowed",
            aiOpen
              ? "bg-gradient-to-r from-accent-primary/20 to-transparent text-accent-primary border-accent-primary"
              : "text-text-secondary hover:text-text-primary hover:bg-surface border-transparent"
          )}
        >
          <Sparkles className={cn("w-4 h-4 transition-all", aiOpen && "animate-pulse")} />
          <span className="hidden lg:inline">AI Chat</span>
          {aiOpen && (
            <span className="hidden lg:inline ml-auto text-[9px] font-mono bg-accent-primary/20 text-accent-primary px-1.5 py-0.5 rounded">ON</span>
          )}
        </button>
        {navItem("/settings", "Settings", Settings)}
      </div>
    </aside>
  );
}

function AppInner() {
  const location = useLocation();
  const [aiOpen, setAiOpen] = useState(false);

  // Resolve the current packageId from the URL or fallback
  const urlMatch = location.pathname.match(/\/app\/([^/]+)/);
  const packageId = urlMatch
    ? decodeURIComponent(urlMatch[1])
    : '';

  const toggleAI = () => {
    if (!packageId) return;
    setAiOpen(prev => !prev);
  };

  const onShortcut = useEffectEvent(() => {
    if (packageId) setAiOpen(open => !open);
  });

  // Keyboard shortcut: Cmd+I / Ctrl+I to toggle AI panel
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        onShortcut();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-background-base text-text-primary font-body">
      {/* Left sidebar */}
      <Sidebar aiOpen={aiOpen} onToggleAI={toggleAI} />

      {/* Main content — scrollable, fills space between sidebar and AI panel */}
      <main className="flex-1 overflow-y-auto min-w-0">
        <Suspense fallback={<RouteLoading />}>
          <Routes>
            <Route path="/" element={<Navigate to="/portfolio" replace />} />
            <Route path="/portfolio" element={<PortfolioCommandCenter />} />
            <Route path="/experiments" element={<ExperimentCenter />} />
            <Route path="/actions" element={<ActionLog />} />

            <Route path="/app/:packageId/funnel" element={<FunnelDiagnostics />} />
            <Route path="/app/:packageId/journey" element={<JourneyMap />} />
            <Route path="/app/:packageId/revenue" element={<RevenueMonetization />} />
            <Route path="/app/:packageId/aso" element={<ASOWorkspace />} />

            <Route path="/settings" element={<SystemSettings />} />
          </Routes>
        </Suspense>
      </main>

      {/* Right AI panel — Cursor-style, same height as viewport */}
      {aiOpen && packageId && (
        <div className="fixed inset-y-0 right-0 z-[60] w-[min(400px,calc(100vw-5rem))] xl:static xl:w-[400px] xl:shrink-0 xl:h-screen">
          <Suspense fallback={<div className="h-full border-l border-border-subtle bg-background-base"><RouteLoading /></div>}>
            <AIChatPanel packageId={packageId} onClose={toggleAI} />
          </Suspense>
        </div>
      )}
    </div>
  );
}

function App() {
  return (
    <Router>
      <AppInner />
    </Router>
  );
}

export default App;
