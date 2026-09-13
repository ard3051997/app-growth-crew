import React, { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Activity,
  RefreshCw,
  Server,
  AlertCircle,
  Clock,
  FileText,
  Save,
  Plus,
  Trash2,
  HelpCircle,
  CheckCircle2,
  Smartphone
} from 'lucide-react';
import { api, type AppConfig, type PortfolioApp, type SafetyStatus, type SystemStatus } from '../api';
import { getErrorMessage } from '../utils';

const PREDEFINED_KEYS = [
  'APP_PACKAGE_NAME',
  'GEMINI_API_KEY',
  'GOOGLE_APPLICATION_CREDENTIALS',
  'GA4_PROPERTY_ID',
  'ADMOB_ACCOUNT_ID',
  'ADMOB_TOKEN_PATH',
  'GOOGLE_ADS_CONFIGURATION_FILE_PATH',
  'GCS_PLAY_CONSOLE_BUCKET',
  'REVENUECAT_API_KEY',
  'REVENUECAT_PROJECT_ID',
  'APPFOLLOW_API_KEY',
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID'
];

const APP_SECRET_KEYS = new Set([
  'revenuecat_api_key',
  'app_store_connect_private_key_path',
]);

const isMaskedSecret = (value: unknown) => {
  if (typeof value !== 'string') return false;
  const normalized = value.trim().toLowerCase();
  return /^\*{3,}$/.test(normalized)
    || /^•{3,}$/.test(normalized)
    || ['<redacted>', '[redacted]', '__masked__', 'masked'].includes(normalized);
};

type CustomVariable = { key: string; value: string; persisted: boolean };

const statusPresentation: Record<string, { label: string; dot: string; badge: string }> = {
  success: { label: 'Success', dot: 'bg-success', badge: 'bg-success/10 border-success/20 text-success' },
  running: { label: 'Running', dot: 'bg-info', badge: 'bg-info/10 border-info/20 text-info' },
  partial: { label: 'Partial', dot: 'bg-warning', badge: 'bg-warning/10 border-warning/20 text-warning' },
  stale: { label: 'Stale', dot: 'bg-warning', badge: 'bg-warning/10 border-warning/20 text-warning' },
  unavailable: { label: 'Unavailable', dot: 'bg-danger', badge: 'bg-danger/10 border-danger/20 text-danger' },
};

export default function Settings() {
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [safetyMetrics, setSafetyMetrics] = useState<SafetyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Configuration Editor states
  const [configs, setConfigs] = useState<Record<string, string>>({});
  const [customVars, setCustomVars] = useState<CustomVariable[]>([]);
  const [configLoading, setConfigLoading] = useState(true);
  const [configError, setConfigError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const systemConfigDirtyKeys = useRef(new Set<string>());

  const serviceNames: Record<string, string> = {
    analytics: 'GA4 Analytics MCP',
    play_store: 'Google Play Store MCP',
    revenuecat: 'RevenueCat Subscriber API',
    admob: 'Google AdMob Reporting API',
    aso: 'App Store ASO Keywords MCP',
    google_ads: 'Google Ads API / MCP',
    gcs: 'Google Cloud Storage MCP',
    funnel_engine: 'Funnel Engine Daemon',
    fcm_push: 'FCM Push & Alerts Gateway',
    journey_map: 'Journey Map Agent'
  };

  const fetchSystemData = () => {
    setLoading(true);
    Promise.all([api.getSystemStatus(), api.getSystemSafety()])
      .then(([status, safety]) => {
        setSystemStatus(status);
        setSafetyMetrics(safety);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setError(getErrorMessage(err, 'Failed to load system settings'));
        setLoading(false);
      });
  };

  const fetchConfigData = () => {
    setConfigLoading(true);
    api.getSystemConfig()
      .then(res => {
        const predefined: Record<string, string> = {};
        const custom: CustomVariable[] = [];
        Object.entries(res.configs || {}).forEach(([key, val]) => {
          if (PREDEFINED_KEYS.includes(key)) {
            predefined[key] = val as string;
          } else {
            custom.push({ key, value: val as string, persisted: true });
          }
        });
        setConfigs(predefined);
        setCustomVars(custom);
        systemConfigDirtyKeys.current.clear();
        setConfigLoading(false);
      })
      .catch(err => {
        console.error(err);
        setConfigError(getErrorMessage(err, 'Failed to load system environment variables'));
        setConfigLoading(false);
      });
  };

  useEffect(() => {
    let active = true;
    Promise.all([api.getSystemStatus(), api.getSystemSafety()])
      .then(([status, safety]) => {
        if (!active) return;
        setSystemStatus(status);
        setSafetyMetrics(safety);
        setLoading(false);
      })
      .catch(err => {
        if (!active) return;
        setError(getErrorMessage(err, 'Failed to load system settings'));
        setLoading(false);
      });
    api.getSystemConfig()
      .then(result => {
        if (!active) return;
        const predefined: Record<string, string> = {};
        const custom: CustomVariable[] = [];
        Object.entries(result.configs || {}).forEach(([key, value]) => {
          if (PREDEFINED_KEYS.includes(key)) predefined[key] = value;
          else custom.push({ key, value, persisted: true });
        });
        setConfigs(predefined);
        setCustomVars(custom);
        systemConfigDirtyKeys.current.clear();
        setConfigLoading(false);
      })
      .catch(err => {
        if (!active) return;
        setConfigError(getErrorMessage(err, 'Failed to load system environment variables'));
        setConfigLoading(false);
      });
    return () => { active = false; };
  }, []);

  const handlePredefinedChange = (key: string, val: string) => {
    systemConfigDirtyKeys.current.add(key);
    setConfigs(prev => ({ ...prev, [key]: val }));
  };

  const handleCustomChange = (index: number, field: 'key' | 'value', val: string) => {
    setCustomVars(prev => {
      const updated = [...prev];
      if (updated[index].persisted) systemConfigDirtyKeys.current.add(updated[index].key);
      updated[index][field] = val;
      return updated;
    });
  };

  const addCustomVar = () => {
    setCustomVars(prev => [...prev, { key: '', value: '', persisted: false }]);
  };

  const removeCustomVar = (index: number) => {
    setCustomVars(prev => {
      const variable = prev[index];
      if (variable.persisted) {
        systemConfigDirtyKeys.current.add(variable.key);
        return prev.map((item, itemIndex) => itemIndex === index ? { ...item, value: '' } : item);
      }
      return prev.filter((_, itemIndex) => itemIndex !== index);
    });
  };

  // --- Per-app config state ---
  const [appList, setAppList] = useState<Pick<PortfolioApp, 'package_name' | 'display_name'>[]>([]);
  const [selectedApp, setSelectedApp] = useState<string>('');
  const [appConfig, setAppConfig] = useState<AppConfig>({});
  const [appConfigLoading, setAppConfigLoading] = useState(false);
  const [appConfigSaving, setAppConfigSaving] = useState(false);
  const [appConfigSuccess, setAppConfigSuccess] = useState<string | null>(null);
  const [appConfigError, setAppConfigError] = useState<string | null>(null);
  const appSelectionGeneration = useRef(0);
  const appConfigDirtyKeys = useRef(new Set<string>());
  const appConfigRequest = useRef<AbortController | null>(null);
  const appSaveRequest = useRef<AbortController | null>(null);
  const eventsGenerationRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    api.getPortfolio()
      .then(res => setAppList(res.apps || []))
      .catch(() => {});
    return () => {
      appConfigRequest.current?.abort();
      appSaveRequest.current?.abort();
      eventsGenerationRequest.current?.abort();
    };
  }, []);

  const isIosApp = (pkg: string) =>
    /-id\d+$/.test(pkg) || /^\d+$/.test(pkg);

  const handleAppSelect = (pkg: string) => {
    const generation = ++appSelectionGeneration.current;
    appConfigRequest.current?.abort();
    appSaveRequest.current?.abort();
    eventsGenerationRequest.current?.abort();
    setSelectedApp(pkg);
    setAppConfig({});
    appConfigDirtyKeys.current.clear();
    setAppConfigSuccess(null);
    setAppConfigError(null);
    setAppConfigSaving(false);
    setEventsZipFile(null);
    setEventsGenResult(null);
    setEventsGenError(null);
    setEventsGenerating(false);
    if (!pkg) {
      setAppConfigLoading(false);
      return;
    }
    const controller = new AbortController();
    appConfigRequest.current = controller;
    setAppConfigLoading(true);
    api.getAppConfig(pkg, controller.signal)
      .then(data => {
        if (appSelectionGeneration.current !== generation) return;
        setAppConfig(data);
        setAppConfigLoading(false);
      })
      .catch(err => {
        if (controller.signal.aborted || appSelectionGeneration.current !== generation) return;
        setAppConfigError(getErrorMessage(err, 'Failed to load app configuration.'));
        setAppConfigLoading(false);
      });
  };

  const handleAppConfigChange = (key: string, val: string) => {
    appConfigDirtyKeys.current.add(key);
    setAppConfig(prev => ({ ...prev, [key]: val === '' ? null : val }));
  };

  const appConfigInputValue = (key: string) => {
    const value = appConfig[key];
    return APP_SECRET_KEYS.has(key) && isMaskedSecret(value) ? '' : String(value ?? '');
  };

  const saveAppConfig = () => {
    if (!selectedApp) return;
    const packageName = selectedApp;
    const generation = appSelectionGeneration.current;
    const fields = Object.fromEntries(
      [...appConfigDirtyKeys.current]
        .filter(key => !(APP_SECRET_KEYS.has(key) && isMaskedSecret(appConfig[key])))
        .map(key => [key, appConfig[key] ?? null])
    ) as AppConfig;
    if (Object.keys(fields).length === 0) {
      setAppConfigSuccess('No app configuration changes to save. Masked secrets were left unchanged.');
      return;
    }
    appSaveRequest.current?.abort();
    const controller = new AbortController();
    appSaveRequest.current = controller;
    setAppConfigSaving(true);
    setAppConfigSuccess(null);
    setAppConfigError(null);
    api.updateAppConfig(packageName, fields, controller.signal)
      .then(() => {
        if (controller.signal.aborted || appSelectionGeneration.current !== generation) return;
        Object.keys(fields).forEach(key => appConfigDirtyKeys.current.delete(key));
        setAppConfigSuccess('App configuration saved successfully.');
        setAppConfigSaving(false);
      })
      .catch(err => {
        if (controller.signal.aborted || appSelectionGeneration.current !== generation) return;
        setAppConfigError(getErrorMessage(err, 'Failed to save app configuration.'));
        setAppConfigSaving(false);
      });
  };

  // --- ZIP → EVENTS.md generation state ---
  const [eventsZipFile, setEventsZipFile] = useState<File | null>(null);
  const [eventsGenerating, setEventsGenerating] = useState(false);
  const [eventsGenResult, setEventsGenResult] = useState<{ path: string; journey_count: number } | null>(null);
  const [eventsGenError, setEventsGenError] = useState<string | null>(null);

  const handleGenerateEvents = () => {
    if (!eventsZipFile || !selectedApp) return;
    const packageName = selectedApp;
    const generation = appSelectionGeneration.current;
    const zipFile = eventsZipFile;
    eventsGenerationRequest.current?.abort();
    const controller = new AbortController();
    eventsGenerationRequest.current = controller;
    setEventsGenerating(true);
    setEventsGenResult(null);
    setEventsGenError(null);
    api.generateEventsFromZip(packageName, zipFile, controller.signal)
      .then(res => {
        if (controller.signal.aborted || appSelectionGeneration.current !== generation) return;
        setEventsGenResult({ path: res.path, journey_count: res.journey_count });
        appConfigDirtyKeys.current.add('events_md_path');
        setAppConfig(prev => ({ ...prev, events_md_path: res.path }));
        setEventsGenerating(false);
      })
      .catch(err => {
        if (controller.signal.aborted || appSelectionGeneration.current !== generation) return;
        setEventsGenError(getErrorMessage(err, 'Generation failed.'));
        setEventsGenerating(false);
      });
  };

  const saveConfiguration = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveSuccess(null);
    setConfigError(null);

    const finalConfigs: Record<string, string> = {};
    let validationFailed = false;

    Object.entries(configs).forEach(([key, value]) => {
      if (systemConfigDirtyKeys.current.has(key) && !isMaskedSecret(value)) finalConfigs[key] = value;
    });

    customVars.forEach(({ key, value, persisted }, index) => {
      const trimmedKey = key.trim();
      if (trimmedKey) {
        if (!/^[A-Z0-9_]+$/.test(trimmedKey)) {
          setConfigError(`Invalid custom key format at row ${index + 1}. Keys must only contain uppercase letters, numbers, and underscores.`);
          validationFailed = true;
          return;
        }
        if ((!persisted || systemConfigDirtyKeys.current.has(trimmedKey)) && !isMaskedSecret(value)) {
          finalConfigs[trimmedKey] = value;
        }
      }
    });

    if (validationFailed) {
      setIsSaving(false);
      return;
    }

    if (Object.keys(finalConfigs).length === 0) {
      setSaveSuccess('No configuration changes to save. Masked secrets were left unchanged.');
      setIsSaving(false);
      return;
    }

    api.updateSystemConfig(finalConfigs)
      .then(() => {
        systemConfigDirtyKeys.current.clear();
        setCustomVars(previous => previous.map(variable => (
          Object.hasOwn(finalConfigs, variable.key) ? { ...variable, persisted: true } : variable
        )));
        setSaveSuccess('Configuration updated. Existing keys are retained by the backend; blank values clear their contents.');
        setIsSaving(false);
        // Refresh statuses in case they changed
        fetchSystemData();
      })
      .catch(err => {
        console.error(err);
        setConfigError(getErrorMessage(err, 'Failed to update system configurations'));
        setIsSaving(false);
      });
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const services = Object.entries(systemStatus?.services || {}).map(([key, status]) => ({
    name: serviceNames[key] || key.replace('_', ' ').toUpperCase(),
    key,
    status: status as string
  }));

  return (
    <div className="p-8 max-w-[1400px] mx-auto min-h-screen relative overflow-hidden">
      {/* Glow ambient */}
      <div className="absolute top-[-10%] right-[-10%] w-[35%] h-[35%] bg-accent-primary/10 rounded-full blur-[100px] pointer-events-none" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[35%] h-[35%] bg-accent-secondary/5 rounded-full blur-[100px] pointer-events-none" />

      <header className="mb-8 flex justify-between items-end z-10 relative">
        <div>
          <h1 className="text-3xl font-heading font-bold mb-2">System Settings & Configurations</h1>
          <p className="text-text-secondary">Inspect observed source and scheduler health, review safety thresholds, and edit allowlisted `.env` variables.</p>
        </div>
        <button
          onClick={() => {
            fetchSystemData();
            fetchConfigData();
          }}
          className="flex items-center gap-2 bg-surface hover:bg-white/5 border border-border-subtle text-text-primary px-4 py-2 rounded-lg text-sm font-medium transition-all"
        >
          <RefreshCw className="w-4 h-4 animate-spin-slow" /> Sync System
        </button>
      </header>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger text-sm p-4 rounded-lg flex items-center gap-3 mb-6 z-10 relative">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 z-10 relative mb-8">

        {/* Connected Services */}
        <div className="glass-card p-6 space-y-6 lg:col-span-2">
          <h2 className="text-lg font-heading font-bold flex items-center gap-2 border-b border-border-subtle pb-3">
            <Server className="w-5 h-5 text-accent-secondary" /> Observed MCP Servers & Services
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {services.map((svc) => {
              const presentation = statusPresentation[svc.status] || statusPresentation.unavailable;
              return (
                <div key={svc.key} className="flex justify-between items-center bg-surface border border-border-subtle p-4 rounded-xl">
                  <div className="flex items-center gap-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${presentation.dot} ${svc.status === 'running' ? 'animate-pulse' : ''}`} />
                    <span className="text-sm font-medium text-text-primary">{svc.name}</span>
                  </div>
                  <span className={`text-[10px] font-mono font-bold px-2.5 py-1 rounded-full uppercase tracking-wider border ${presentation.badge}`}>
                    {presentation.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Safety Thresholds */}
        <div className="glass-card p-6 space-y-6">
          <h2 className="text-lg font-heading font-bold flex items-center gap-2 border-b border-border-subtle pb-3">
            <Shield className="w-5 h-5 text-danger" /> Safety Monitor Parameters
          </h2>

          <div className="space-y-4 font-mono text-xs">
            <div className="flex justify-between items-center bg-surface border border-border-subtle p-3 rounded-lg">
              <span className="text-text-secondary">CRASH RATE EMERGENCY TRIGGER</span>
              <span className="text-text-primary font-bold text-sm">
                {safetyMetrics?.crash_threshold != null ? `${safetyMetrics.crash_threshold.toFixed(2)}%` : 'Unavailable'}
              </span>
            </div>
            <div className="flex justify-between items-center bg-surface border border-border-subtle p-3 rounded-lg">
              <span className="text-text-secondary">ANR RATE EMERGENCY TRIGGER</span>
              <span className="text-text-primary font-bold text-sm">
                {safetyMetrics?.anr_threshold != null ? `${safetyMetrics.anr_threshold.toFixed(2)}%` : 'Unavailable'}
              </span>
            </div>
            <div className="flex justify-between items-center bg-surface border border-border-subtle p-3 rounded-lg">
              <span className="text-text-secondary">EMERGENCY BRAKE STATUS</span>
              <span className="text-text-primary font-bold text-sm">
                {safetyMetrics?.emergency_brake || 'Unavailable'}
              </span>
            </div>
          </div>
        </div>

        {/* Daemon Scheduler Schedules */}
        <div className="glass-card p-6 space-y-6">
          <h2 className="text-lg font-heading font-bold flex items-center gap-2 border-b border-border-subtle pb-3">
            <Clock className="w-5 h-5 text-accent-primary" /> Autonomous Daemon Loop
          </h2>

          <div className="space-y-4">
            {(() => {
              const scheduler = systemStatus?.scheduler;
              const presentation = statusPresentation[scheduler?.state || 'unavailable'] || statusPresentation.unavailable;
              return <>
                <div className="flex items-center justify-between rounded-lg border border-border-subtle bg-surface p-3">
                  <span className="text-xs text-text-secondary">Persisted scheduler state</span>
                  <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase ${presentation.badge}`}>{presentation.label}</span>
                </div>
                <div className="space-y-2 text-xs font-mono text-text-secondary">
                  <div>Heartbeat: {scheduler?.heartbeat_at ? new Date(scheduler.heartbeat_at).toLocaleString() : 'Unavailable'}</div>
                  <div>Last cycle completed: {scheduler?.last_cycle_completed_at ? new Date(scheduler.last_cycle_completed_at).toLocaleString() : 'Unavailable'}</div>
                  <div>Last cycle result: {scheduler?.last_cycle_status || 'Unavailable'}</div>
                  {scheduler?.error && <div className="text-danger">{scheduler.error}</div>}
                </div>
              </>;
            })()}
          </div>
        </div>

        {/* System Trust Progression */}
        <div className="glass-card p-6 space-y-6 lg:col-span-2">
          <h2 className="text-lg font-heading font-bold flex items-center gap-2 border-b border-border-subtle pb-3">
            <Activity className="w-5 h-5 text-accent-secondary" /> Trust Tier Criteria
          </h2>

          <div className="space-y-4">
            <div className="flex justify-between items-center border-b border-border-subtle pb-3">
              <div>
                <div className="text-sm font-semibold text-text-primary">Conservative</div>
                <p className="text-xs text-text-muted">ASO metadata changes only; requires full Telegram manual approvals.</p>
              </div>
              <span className="text-xs font-mono text-text-muted">Starting tier</span>
            </div>

            <div className="flex justify-between items-center border-b border-border-subtle pb-3">
              <div>
                <div className="text-sm font-semibold text-text-primary">Moderate</div>
                <p className="text-xs text-text-muted">Enables pricing & ad configurations; metadata auto-approved.</p>
              </div>
              <span className="text-xs font-mono text-accent-secondary font-bold">5+ wins, &lt;20% rollbacks</span>
            </div>

            <div className="flex justify-between items-center">
              <div>
                <div className="text-sm font-semibold text-text-primary">Aggressive</div>
                <p className="text-xs text-text-muted">Enables UA campaign budgets; full autonomous action execution.</p>
              </div>
              <span className="text-xs font-mono text-accent-primary font-bold">15+ wins, &lt;10% rollbacks</span>
            </div>
          </div>
        </div>

      </div>

      {/* Per-App Configuration Card */}
      <div className="glass-card p-6 space-y-6 z-10 relative mb-8">
        <div className="flex justify-between items-center border-b border-border-subtle pb-3">
          <h2 className="text-lg font-heading font-bold flex items-center gap-2">
            <Smartphone className="w-5 h-5 text-accent-primary" /> Per-App Credential Configuration
          </h2>
          <span className="text-xs font-mono bg-white/5 border border-border-subtle px-3 py-1 rounded text-text-muted">
            config/apps.json
          </span>
        </div>

        {/* App selector */}
        <div className="space-y-1.5">
          <label className="text-xs font-mono text-text-secondary">SELECT APP</label>
          <select
            value={selectedApp}
            onChange={(e) => handleAppSelect(e.target.value)}
            className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
          >
            <option value="">— Choose an app —</option>
            {appList.map((a) => (
              <option key={a.package_name} value={a.package_name}>
                {a.display_name} ({a.package_name})
              </option>
            ))}
          </select>
        </div>

        {appConfigLoading && (
          <div className="flex items-center gap-3 py-4">
            <div className="w-5 h-5 border-2 border-accent-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-text-secondary font-mono">Loading app config…</span>
          </div>
        )}

        {selectedApp && !appConfigLoading && (
          <div className="space-y-6">
            {appConfigError && (
              <div className="bg-danger/10 border border-danger/20 text-danger text-sm p-4 rounded-lg flex items-center gap-3">
                <AlertCircle className="w-4 h-4 shrink-0" /><span>{appConfigError}</span>
              </div>
            )}
            {appConfigSuccess && (
              <div className="bg-success/10 border border-success/20 text-success text-sm p-4 rounded-lg flex items-center gap-3">
                <CheckCircle2 className="w-4 h-4 shrink-0" /><span>{appConfigSuccess}</span>
              </div>
            )}

            {/* Google Ads */}
            <div className="space-y-3 pt-2">
              <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                Google Ads
              </h3>
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-text-secondary flex items-center gap-1">
                  google_ads_customer_id
                  <span title="Google Ads customer account ID (e.g. 123-456-7890)"><HelpCircle className="w-3.5 h-3.5 text-text-muted" /></span>
                </label>
                <input
                  type="text"
                  value={String(appConfig['google_ads_customer_id'] ?? '')}
                  onChange={(e) => handleAppConfigChange('google_ads_customer_id', e.target.value)}
                  placeholder="e.g. 499-163-9790"
                  className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                />
              </div>
            </div>

            {/* Journey Map */}
            <div className="space-y-3 pt-2">
              <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                Journey Map
              </h3>

              {/* Manual path input */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-text-secondary flex items-center gap-1">
                  events_md_path
                  <span title="Absolute path to this app's EVENTS.md file. Takes priority over automatic path detection.">
                    <HelpCircle className="w-3.5 h-3.5 text-text-muted" />
                  </span>
                </label>
                <input
                  type="text"
                  value={String(appConfig['events_md_path'] ?? '')}
                  onChange={(e) => handleAppConfigChange('events_md_path', e.target.value)}
                  placeholder="/path/to/docs/com.example.app_EVENTS.md"
                  className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                />
              </div>

              {/* ZIP upload + AI generation */}
              <div className="pt-3 border-t border-border-subtle/60 space-y-3">
                <div className="text-[10px] text-text-muted font-mono uppercase tracking-wider flex items-center gap-2">
                  <div className="flex-1 border-t border-border-subtle/40" />
                  or generate from codebase ZIP
                  <div className="flex-1 border-t border-border-subtle/40" />
                </div>
                <div className="flex gap-2 items-center">
                  <label className="flex-1 flex items-center gap-2 px-3 py-2 bg-surface border border-border-subtle rounded-lg cursor-pointer hover:border-accent-primary/40 transition-colors">
                    <Smartphone className="w-4 h-4 text-text-muted shrink-0" />
                    <span className="text-xs font-mono text-text-secondary truncate">
                      {eventsZipFile ? eventsZipFile.name : 'Choose ZIP file…'}
                    </span>
                    <input
                      key={selectedApp}
                      type="file"
                      accept=".zip"
                      className="hidden"
                      onChange={(e) => {
                        setEventsZipFile(e.target.files?.[0] || null);
                        setEventsGenResult(null);
                        setEventsGenError(null);
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={handleGenerateEvents}
                    disabled={!eventsZipFile || eventsGenerating}
                    className="flex items-center gap-2 bg-accent-primary hover:bg-accent-primary/90 text-white font-medium px-4 py-2 rounded-lg text-xs transition-all disabled:opacity-40 shrink-0"
                  >
                    {eventsGenerating
                      ? <><div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" /> Analyzing…</>
                      : <><Save className="w-3.5 h-3.5" /> Generate</>
                    }
                  </button>
                </div>
                {eventsGenerating && (
                  <p className="text-[11px] text-text-muted font-mono animate-pulse">
                    Scanning source files and generating journey map… this may take 30–60 seconds.
                  </p>
                )}
                {eventsGenResult && (
                  <div className="bg-success/10 border border-success/20 text-success text-xs p-3 rounded-lg flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
                    <div>
                      <div className="font-semibold">Generated {eventsGenResult.journey_count} journey{eventsGenResult.journey_count !== 1 ? 's' : ''}</div>
                      <div className="text-success/70 font-mono text-[10px] mt-0.5 break-all">{eventsGenResult.path}</div>
                    </div>
                  </div>
                )}
                {eventsGenError && (
                  <div className="bg-danger/10 border border-danger/20 text-danger text-xs p-3 rounded-lg flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    <span>{eventsGenError}</span>
                  </div>
                )}
              </div>
            </div>

            {/* RevenueCat */}
            <div className="space-y-3 pt-4 border-t border-border-subtle">
              <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                RevenueCat
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary">revenuecat_api_key</label>
                  <input
                    type="password"
                    value={appConfigInputValue('revenuecat_api_key')}
                    onChange={(e) => handleAppConfigChange('revenuecat_api_key', e.target.value)}
                    placeholder={isMaskedSecret(appConfig['revenuecat_api_key']) ? 'Configured; enter a value only to replace it' : 'sk_…'}
                    className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary">revenuecat_project_id</label>
                  <input
                    type="text"
                    value={String(appConfig['revenuecat_project_id'] ?? '')}
                    onChange={(e) => handleAppConfigChange('revenuecat_project_id', e.target.value)}
                    placeholder="proj…"
                    className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary flex items-center gap-1">
                    rc_platform
                    <span title="Filter RC revenue by store — use when iOS + Android share the same RC project to avoid double-counting">
                      <HelpCircle className="w-3.5 h-3.5 text-text-muted" />
                    </span>
                  </label>
                  <select
                    value={String(appConfig['rc_platform'] ?? '')}
                    onChange={(e) => handleAppConfigChange('rc_platform', e.target.value)}
                    className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                  >
                    <option value="">All platforms (no filter)</option>
                    <option value="play_store">play_store (Android)</option>
                    <option value="app_store">app_store (iOS)</option>
                  </select>
                </div>
              </div>
            </div>

            {/* AdMob & Analytics */}
            <div className="space-y-3 pt-4 border-t border-border-subtle">
              <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                AdMob & Analytics
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary">admob_account_id</label>
                  <input
                    type="text"
                    value={String(appConfig['admob_account_id'] ?? '')}
                    onChange={(e) => handleAppConfigChange('admob_account_id', e.target.value)}
                    placeholder="pub-…"
                    className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary">ga4_property_id</label>
                  <input
                    type="text"
                    value={String(appConfig['ga4_property_id'] ?? '')}
                    onChange={(e) => handleAppConfigChange('ga4_property_id', e.target.value)}
                    placeholder="e.g. 151002871"
                    className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                  />
                </div>
              </div>
            </div>

            {/* Google Cloud — Android only */}
            {!isIosApp(selectedApp) && (
              <div className="space-y-3 pt-4 border-t border-border-subtle">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                  Google Cloud (Android)
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-mono text-text-secondary">google_credentials_path</label>
                    <input
                      type="text"
                      value={String(appConfig['google_credentials_path'] ?? '')}
                      onChange={(e) => handleAppConfigChange('google_credentials_path', e.target.value)}
                      placeholder="/path/to/service-account.json"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-mono text-text-secondary">gcs_play_console_bucket</label>
                    <input
                      type="text"
                      value={String(appConfig['gcs_play_console_bucket'] ?? '')}
                      onChange={(e) => handleAppConfigChange('gcs_play_console_bucket', e.target.value)}
                      placeholder="pubsite_prod_…"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* App Store Connect — iOS only */}
            {isIosApp(selectedApp) && (
              <div className="space-y-3 pt-4 border-t border-border-subtle">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                  App Store Connect (iOS)
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      app_store_connect_key_id
                      <span title="API Key ID from App Store Connect → Keys"><HelpCircle className="w-3.5 h-3.5 text-text-muted" /></span>
                    </label>
                    <input
                      type="text"
                      value={String(appConfig['app_store_connect_key_id'] ?? '')}
                      onChange={(e) => handleAppConfigChange('app_store_connect_key_id', e.target.value)}
                      placeholder="e.g. ABCDE12345"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      app_store_connect_issuer_id
                      <span title="Issuer UUID from App Store Connect → Keys"><HelpCircle className="w-3.5 h-3.5 text-text-muted" /></span>
                    </label>
                    <input
                      type="text"
                      value={String(appConfig['app_store_connect_issuer_id'] ?? '')}
                      onChange={(e) => handleAppConfigChange('app_store_connect_issuer_id', e.target.value)}
                      placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      app_store_connect_private_key_path
                      <span title="Absolute path to the downloaded .p8 private key file"><HelpCircle className="w-3.5 h-3.5 text-text-muted" /></span>
                    </label>
                    <input
                      type="text"
                      value={appConfigInputValue('app_store_connect_private_key_path')}
                      onChange={(e) => handleAppConfigChange('app_store_connect_private_key_path', e.target.value)}
                      placeholder={isMaskedSecret(appConfig['app_store_connect_private_key_path']) ? 'Configured; enter a value only to replace it' : '/path/to/AuthKey_ABCDE12345.p8'}
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      team_id
                      <span title="Apple Developer Team ID (10-character alphanumeric)"><HelpCircle className="w-3.5 h-3.5 text-text-muted" /></span>
                    </label>
                    <input
                      type="text"
                      value={String(appConfig['team_id'] ?? '')}
                      onChange={(e) => handleAppConfigChange('team_id', e.target.value)}
                      placeholder="e.g. ABCDE12345"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                </div>
              </div>
            )}

            <div className="pt-4 flex justify-end">
              <button
                type="button"
                onClick={saveAppConfig}
                disabled={appConfigSaving}
                className="flex items-center gap-2 bg-accent-primary hover:bg-accent-primary/90 text-white font-medium px-6 py-2.5 rounded-lg text-sm transition-all disabled:opacity-50"
              >
                {appConfigSaving
                  ? <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> Saving…</>
                  : <><Save className="w-4 h-4" /> Save App Config</>
                }
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Configuration Form Card */}
      <div className="glass-card p-6 space-y-6 z-10 relative">
        <div className="flex justify-between items-center border-b border-border-subtle pb-3">
          <h2 className="text-lg font-heading font-bold flex items-center gap-2">
            <FileText className="w-5 h-5 text-accent-primary" /> Environment Configuration Editor (.env)
          </h2>
          <span className="text-xs font-mono bg-white/5 border border-border-subtle px-3 py-1 rounded text-text-muted">
            Locally Saved Variables
          </span>
        </div>

        {configLoading ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <div className="w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-text-secondary font-mono">Loading environment properties...</p>
          </div>
        ) : (
          <form onSubmit={saveConfiguration} className="space-y-8">
            {configError && (
              <div className="bg-danger/10 border border-danger/20 text-danger text-sm p-4 rounded-lg flex items-center gap-3">
                <AlertCircle className="w-5 h-5 shrink-0" />
                <span>{configError}</span>
              </div>
            )}

            {saveSuccess && (
              <div className="bg-success/10 border border-success/20 text-success text-sm p-4 rounded-lg flex items-center gap-3">
                <CheckCircle2 className="w-5 h-5 shrink-0" />
                <span>{saveSuccess}</span>
              </div>
            )}

            <div className="space-y-6">

              {/* Group 1: Core & AI */}
              <div className="space-y-4">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                  1. Core & AI Settings
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-1.5">
                    <label htmlFor="APP_PACKAGE_NAME" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      APP_PACKAGE_NAME
                      <span title="Active app target package name"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="APP_PACKAGE_NAME"
                      value={configs['APP_PACKAGE_NAME'] || ''}
                      onChange={(e) => handlePredefinedChange('APP_PACKAGE_NAME', e.target.value)}
                      placeholder="e.g. com.finance.loan.emicalculator"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="GEMINI_API_KEY" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      GEMINI_API_KEY
                      <span title="Google Gemini API key for coordinator agent"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="password"
                      id="GEMINI_API_KEY"
                      value={configs['GEMINI_API_KEY'] || ''}
                      onChange={(e) => handlePredefinedChange('GEMINI_API_KEY', e.target.value)}
                      placeholder="Enter Gemini API key"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Group 2: Google Ecosystem */}
              <div className="space-y-4 pt-4 border-t border-border-subtle">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                  2. Google Play, AdMob, Analytics & Ads
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-1.5">
                    <label htmlFor="GOOGLE_APPLICATION_CREDENTIALS" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      GOOGLE_APPLICATION_CREDENTIALS
                      <span title="Absolute path to Google service account JSON file"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="GOOGLE_APPLICATION_CREDENTIALS"
                      value={configs['GOOGLE_APPLICATION_CREDENTIALS'] || ''}
                      onChange={(e) => handlePredefinedChange('GOOGLE_APPLICATION_CREDENTIALS', e.target.value)}
                      placeholder="e.g. /path/to/service-account.json"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="GA4_PROPERTY_ID" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      GA4_PROPERTY_ID
                      <span title="Google Analytics 4 Property ID"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="GA4_PROPERTY_ID"
                      value={configs['GA4_PROPERTY_ID'] || ''}
                      onChange={(e) => handlePredefinedChange('GA4_PROPERTY_ID', e.target.value)}
                      placeholder="e.g. 151002871"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="ADMOB_ACCOUNT_ID" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      ADMOB_ACCOUNT_ID
                      <span title="Google AdMob Publisher ID (pub-xxxxxxxxxxxx)"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="ADMOB_ACCOUNT_ID"
                      value={configs['ADMOB_ACCOUNT_ID'] || ''}
                      onChange={(e) => handlePredefinedChange('ADMOB_ACCOUNT_ID', e.target.value)}
                      placeholder="e.g. pub-9800009975517669"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="ADMOB_TOKEN_PATH" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      ADMOB_TOKEN_PATH
                      <span title="Absolute path to AdMob OAuth credential token file"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="ADMOB_TOKEN_PATH"
                      value={configs['ADMOB_TOKEN_PATH'] || ''}
                      onChange={(e) => handlePredefinedChange('ADMOB_TOKEN_PATH', e.target.value)}
                      placeholder="e.g. /path/to/token.json"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="GOOGLE_ADS_CONFIGURATION_FILE_PATH" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      GOOGLE_ADS_CONFIGURATION_FILE_PATH
                      <span title="Absolute path to google-ads.yaml configuration file"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="GOOGLE_ADS_CONFIGURATION_FILE_PATH"
                      value={configs['GOOGLE_ADS_CONFIGURATION_FILE_PATH'] || ''}
                      onChange={(e) => handlePredefinedChange('GOOGLE_ADS_CONFIGURATION_FILE_PATH', e.target.value)}
                      placeholder="e.g. /path/to/config/google-ads.yaml"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="GCS_PLAY_CONSOLE_BUCKET" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      GCS_PLAY_CONSOLE_BUCKET
                      <span title="Google Cloud Storage bucket name for Play Console reports"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="GCS_PLAY_CONSOLE_BUCKET"
                      value={configs['GCS_PLAY_CONSOLE_BUCKET'] || ''}
                      onChange={(e) => handlePredefinedChange('GCS_PLAY_CONSOLE_BUCKET', e.target.value)}
                      placeholder="e.g. pubsite_prod_6540145348460836433"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Group 3: Subscriptions & keywords */}
              <div className="space-y-4 pt-4 border-t border-border-subtle">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                  3. RevenueCat & AppFollow ASO Settings
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div className="space-y-1.5">
                    <label htmlFor="REVENUECAT_API_KEY" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      REVENUECAT_API_KEY
                      <span title="Secret RevenueCat API key"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="password"
                      id="REVENUECAT_API_KEY"
                      value={configs['REVENUECAT_API_KEY'] || ''}
                      onChange={(e) => handlePredefinedChange('REVENUECAT_API_KEY', e.target.value)}
                      placeholder="sk_..."
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="REVENUECAT_PROJECT_ID" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      REVENUECAT_PROJECT_ID
                      <span title="RevenueCat Project ID"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="REVENUECAT_PROJECT_ID"
                      value={configs['REVENUECAT_PROJECT_ID'] || ''}
                      onChange={(e) => handlePredefinedChange('REVENUECAT_PROJECT_ID', e.target.value)}
                      placeholder="e.g. proj21f88bc8"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="APPFOLLOW_API_KEY" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      APPFOLLOW_API_KEY
                      <span title="AppFollow integration credentials for ASO indexing"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="password"
                      id="APPFOLLOW_API_KEY"
                      value={configs['APPFOLLOW_API_KEY'] || ''}
                      onChange={(e) => handlePredefinedChange('APPFOLLOW_API_KEY', e.target.value)}
                      placeholder="Enter AppFollow token"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Group 4: Alerts */}
              <div className="space-y-4 pt-4 border-t border-border-subtle">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                  4. Telegram Alert Integration
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-1.5">
                    <label htmlFor="TELEGRAM_BOT_TOKEN" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      TELEGRAM_BOT_TOKEN
                      <span title="Telegram Bot API Token (e.g. 123456:ABC...)"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="TELEGRAM_BOT_TOKEN"
                      value={configs['TELEGRAM_BOT_TOKEN'] || ''}
                      onChange={(e) => handlePredefinedChange('TELEGRAM_BOT_TOKEN', e.target.value)}
                      placeholder="Enter Telegram bot token"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="TELEGRAM_CHAT_ID" className="text-xs font-mono text-text-secondary flex items-center gap-1">
                      TELEGRAM_CHAT_ID
                      <span title="Target chat/channel ID to push execution notices"><HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-text-primary cursor-help" /></span>
                    </label>
                    <input
                      type="text"
                      id="TELEGRAM_CHAT_ID"
                      value={configs['TELEGRAM_CHAT_ID'] || ''}
                      onChange={(e) => handlePredefinedChange('TELEGRAM_CHAT_ID', e.target.value)}
                      placeholder="e.g. 819418525"
                      className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Group 5: Custom Variables */}
              <div className="space-y-4 pt-4 border-t border-border-subtle">
                <div className="flex justify-between items-center">
                  <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-accent-secondary">
                    5. Custom / Optional variables
                  </h3>
                  <button
                    type="button"
                    onClick={addCustomVar}
                    className="flex items-center gap-1 bg-surface hover:bg-white/5 border border-border-subtle text-text-primary text-xs px-2.5 py-1.5 rounded-lg font-medium transition-all"
                  >
                    <Plus className="w-3.5 h-3.5" /> Add Variable
                  </button>
                </div>

                <p className="text-[11px] text-text-muted font-mono">
                  This backend cannot delete environment keys. Clearing a persisted value saves `KEY=`; only unsaved rows can be removed entirely.
                </p>

                <div className="space-y-3">
                  {customVars.map((v, idx) => (
                    <div key={idx} className="flex gap-4 items-center bg-surface/30 p-3.5 rounded-xl border border-border-subtle">
                      <div className="flex-1 space-y-1">
                        <input
                          type="text"
                          value={v.key}
                          onChange={(e) => handleCustomChange(idx, 'key', e.target.value)}
                          disabled={v.persisted}
                          placeholder="VARIABLE_NAME"
                          className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-1.5 text-xs text-text-primary outline-none focus:border-accent-primary font-mono uppercase disabled:opacity-60 disabled:cursor-not-allowed"
                        />
                      </div>
                      <span className="text-text-muted font-mono text-sm">=</span>
                      <div className="flex-[2] space-y-1">
                        <input
                          type="text"
                          value={v.value}
                          onChange={(e) => handleCustomChange(idx, 'value', e.target.value)}
                          placeholder="value"
                          className="w-full bg-surface border border-border-subtle rounded-lg px-3 py-1.5 text-xs text-text-primary outline-none focus:border-accent-primary font-mono"
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => removeCustomVar(idx)}
                        className="p-2 hover:bg-danger/10 border border-transparent hover:border-danger/20 text-text-muted hover:text-danger rounded-lg transition-all"
                        title={v.persisted ? 'Clear value (backend retains the key)' : 'Remove unsaved variable'}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}

                  {customVars.length === 0 && (
                    <div className="text-center py-6 text-text-muted font-mono text-xs italic bg-surface/10 rounded-xl border border-dashed border-border-subtle">
                      No custom properties added.
                    </div>
                  )}
                </div>
              </div>

            </div>

            {/* Actions */}
            <div className="pt-6 border-t border-border-subtle flex justify-end gap-4">
              <button
                type="button"
                onClick={fetchConfigData}
                className="bg-surface hover:bg-white/5 border border-border-subtle text-text-secondary hover:text-text-primary px-5 py-2.5 rounded-lg text-sm font-semibold transition-all"
              >
                Reset Form
              </button>
              <button
                type="submit"
                disabled={isSaving}
                className="flex items-center justify-center gap-2 bg-accent-primary hover:bg-accent-primary/90 disabled:bg-accent-primary/50 text-white px-6 py-2.5 rounded-lg text-sm font-semibold transition-all"
              >
                {isSaving ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Saving Configuration...
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" /> Save Configuration
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>

    </div>
  );
}
