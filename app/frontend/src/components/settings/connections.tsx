import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { connectionsApi, type ConnectionsStatus, type TradingConfigUpdate } from '@/services/connections-api';
import {
  Activity,
  AlertTriangle,
  ArrowRightLeft,
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  ExternalLink,
  Globe,
  Key,
  Loader2,
  LogIn,
  RefreshCw,
  Shield,
  User,
  Wallet,
  WifiOff,
  Zap,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <Badge variant={ok ? 'success' : 'destructive'} className="text-[11px] gap-1">
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-300' : 'bg-red-300'}`} />
      {label}
    </Badge>
  );
}

function SectionToggle({
  title,
  icon: Icon,
  open,
  onToggle,
  badge,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  open: boolean;
  onToggle: () => void;
  badge?: React.ReactNode;
}) {
  return (
    <button
      onClick={onToggle}
      className="w-full flex items-center gap-3 py-3 px-4 text-left hover:bg-muted/50 rounded-lg transition-colors"
    >
      <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      <span className="text-sm font-medium text-primary flex-1">{title}</span>
      {badge}
      {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
    </button>
  );
}

export function ConnectionsSettings() {
  const [status, setStatus] = useState<ConnectionsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testingZerodha, setTestingZerodha] = useState(false);
  const [zerodhaTestResult, setZerodhaTestResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // Expandable sections
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    zerodha: true,
    trading: false,
    risk: false,
    scheduler: false,
    model: false,
    apiStatus: false,
  });

  // Kite Connect form state
  const [kiteApiKey, setKiteApiKey] = useState('');
  const [kiteApiSecret, setKiteApiSecret] = useState('');
  const [requestToken, setRequestToken] = useState('');
  const [kiteLoginUrl, setKiteLoginUrl] = useState<string | null>(null);
  const [kiteLoginLoading, setKiteLoginLoading] = useState(false);
  const [kiteTokenLoading, setKiteTokenLoading] = useState(false);
  const [riskForm, setRiskForm] = useState({
    max_position_pct: 0.1,
    max_portfolio_exposure: 0.8,
    max_single_order_value: 100000,
    max_daily_loss_pct: 0.03,
    max_open_positions: 15,
    stop_loss_pct: 0.05,
    take_profit_pct: 0.15,
  });
  const [schedulerForm, setSchedulerForm] = useState({
    analysis_interval_minutes: 5,
  });
  const [modelForm, setModelForm] = useState({
    model_name: '',
    model_provider: '',
  });

  const toggleSection = (id: string) =>
    setOpenSections((p) => ({ ...p, [id]: !p[id] }));

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const s = await connectionsApi.getStatus();
      setStatus(s);
      setRiskForm({
        max_position_pct: s.risk.max_position_pct,
        max_portfolio_exposure: s.risk.max_portfolio_exposure,
        max_single_order_value: s.risk.max_single_order_value,
        max_daily_loss_pct: s.risk.max_daily_loss_pct,
        max_open_positions: s.risk.max_open_positions,
        stop_loss_pct: s.risk.stop_loss_pct,
        take_profit_pct: s.risk.take_profit_pct,
      });
      setSchedulerForm({
        analysis_interval_minutes: s.scheduler.analysis_interval_minutes,
      });
      setModelForm({
        model_name: s.model.name,
        model_provider: s.model.provider,
      });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleTestZerodha = async () => {
    setTestingZerodha(true);
    setZerodhaTestResult(null);
    try {
      const r = await connectionsApi.testZerodha();
      setZerodhaTestResult({
        ok: r.connected,
        msg: r.connected
          ? `Connected as ${r.user_name || r.user_id || 'user'} — Cash: ₹${(r.funds?.available_cash ?? 0).toLocaleString('en-IN')}`
          : r.error || 'Not connected',
      });
    } catch (e: any) {
      setZerodhaTestResult({ ok: false, msg: e.message });
    } finally {
      setTestingZerodha(false);
    }
  };

  const handleSaveKiteCredentials = async () => {
    if (!kiteApiKey.trim() || !kiteApiSecret.trim()) return;
    setKiteLoginLoading(true);
    try {
      const r = await connectionsApi.saveKiteCredentials(kiteApiKey.trim(), kiteApiSecret.trim());
      setKiteLoginUrl(r.login_url);
      setSaveMsg('Credentials saved — now click Login to authenticate');
      setTimeout(() => setSaveMsg(null), 3000);
      refresh();
    } catch (e: any) {
      setSaveMsg(`Error: ${e.message}`);
    } finally {
      setKiteLoginLoading(false);
    }
  };

  const handleOpenKiteLogin = async () => {
    try {
      if (kiteLoginUrl) {
        window.open(kiteLoginUrl, '_blank');
      } else {
        const r = await connectionsApi.getLoginUrl();
        window.open(r.login_url, '_blank');
      }
    } catch (e: any) {
      setSaveMsg(`Error: ${e.message}`);
    }
  };

  const handleExchangeToken = async () => {
    if (!requestToken.trim()) return;
    setKiteTokenLoading(true);
    try {
      const r = await connectionsApi.exchangeToken(requestToken.trim());
      if (r.error) {
        setSaveMsg(`Token error: ${r.error}`);
      } else {
        setSaveMsg(`Logged in as ${r.user_name || 'user'}`);
        setRequestToken('');
        refresh();
      }
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (e: any) {
      setSaveMsg(`Error: ${e.message}`);
    } finally {
      setKiteTokenLoading(false);
    }
  };

  const handleSaveTradingConfig = async (update: TradingConfigUpdate) => {
    setSaving(true);
    try {
      await connectionsApi.updateTradingConfig(update);
      setSaveMsg('Config saved');
      setTimeout(() => setSaveMsg(null), 2000);
      refresh();
    } catch (e: any) {
      setSaveMsg(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleModeSwitch = async (mode: 'paper' | 'live') => {
    if (mode === 'live') {
      const confirmed = window.confirm(
        'WARNING: Switching to LIVE mode will execute REAL trades with real money.\n\nAre you sure?'
      );
      if (!confirmed) return;
    }
    await handleSaveTradingConfig({ mode });
  };

  if (loading && !status) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-semibold text-primary mb-2">Connections & Trading</h2>
          <p className="text-sm text-muted-foreground">Loading connection status...</p>
        </div>
        <Card className="bg-panel border-gray-700">
          <CardContent className="p-6 flex items-center gap-3">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Checking connections...</span>
          </CardContent>
        </Card>
      </div>
    );
  }

  const mode = status?.trading.mode ?? 'paper';
  const zerodhaConnected = status?.zerodha.connected ?? false;
  const activeKeys = status?.active_providers ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-primary mb-2">Connections & Trading</h2>
          <p className="text-sm text-muted-foreground">
            Manage broker connections, trading mode, risk parameters, and system configuration.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <Card className="bg-red-500/5 border-red-500/20">
          <CardContent className="p-4 flex items-center gap-3">
            <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0" />
            <span className="text-sm text-red-400">{error}</span>
          </CardContent>
        </Card>
      )}

      {saveMsg && (
        <Card className={`${saveMsg.startsWith('Error') ? 'bg-red-500/5 border-red-500/20' : 'bg-emerald-500/5 border-emerald-500/20'}`}>
          <CardContent className="p-3 flex items-center gap-2">
            <Check className="h-4 w-4 text-emerald-500" />
            <span className="text-sm">{saveMsg}</span>
          </CardContent>
        </Card>
      )}

      {/* ── Quick Status Overview ───────────────────────────────── */}
      <Card className="bg-panel border-gray-700">
        <CardContent className="p-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="text-center space-y-1">
              <div className="flex justify-center">
                {zerodhaConnected ? (
                  <Wallet className="h-5 w-5 text-emerald-500" />
                ) : (
                  <WifiOff className="h-5 w-5 text-red-500" />
                )}
              </div>
              <div className="text-xs text-muted-foreground">Zerodha</div>
              <StatusBadge ok={zerodhaConnected} label={zerodhaConnected ? 'Connected' : 'Disconnected'} />
            </div>
            <div className="text-center space-y-1">
              <div className="flex justify-center">
                <ArrowRightLeft className={`h-5 w-5 ${mode === 'live' ? 'text-amber-500' : 'text-blue-500'}`} />
              </div>
              <div className="text-xs text-muted-foreground">Mode</div>
              <Badge variant={mode === 'live' ? 'warning' : 'success'} className="text-[11px]">
                {mode.toUpperCase()}
              </Badge>
            </div>
            <div className="text-center space-y-1">
              <div className="flex justify-center">
                <Key className="h-5 w-5 text-blue-500" />
              </div>
              <div className="text-xs text-muted-foreground">API Keys</div>
              <Badge variant="secondary" className="text-[11px]">
                {activeKeys.length} active
              </Badge>
            </div>
            <div className="text-center space-y-1">
              <div className="flex justify-center">
                <Activity className={`h-5 w-5 ${status?.trading.trader_running ? 'text-emerald-500' : 'text-muted-foreground'}`} />
              </div>
              <div className="text-xs text-muted-foreground">Trader</div>
              <StatusBadge ok={status?.trading.trader_running ?? false} label={status?.trading.trader_running ? 'Running' : 'Stopped'} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Zerodha Kite Connect ──────────────────────────────── */}
      <Card className="bg-panel border-gray-700">
        <SectionToggle
          title="Zerodha Kite Connect"
          icon={Wallet}
          open={openSections.zerodha}
          onToggle={() => toggleSection('zerodha')}
          badge={<StatusBadge ok={zerodhaConnected} label={zerodhaConnected ? 'Connected' : 'Disconnected'} />}
        />
        {openSections.zerodha && (
          <CardContent className="px-4 pb-4 space-y-4">

            {/* Connected profile */}
            {zerodhaConnected && status?.zerodha && (
              <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3 space-y-3">
                <div className="flex items-center gap-3">
                  <User className="h-4 w-4 text-emerald-500" />
                  <div>
                    <div className="text-sm font-medium text-primary">
                      {status.zerodha.user_name || status.zerodha.user_id || 'Connected'}
                    </div>
                    {status.zerodha.email && (
                      <div className="text-[10px] text-muted-foreground">{status.zerodha.email}</div>
                    )}
                  </div>
                  <StatusBadge ok label="Live" />
                </div>
              </div>
            )}

            {/* Not connected — show setup steps */}
            {!zerodhaConnected && (
              <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg p-3">
                <div className="flex items-start gap-2 mb-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 flex-shrink-0" />
                  <div className="text-xs text-amber-500">
                    {!status?.zerodha.has_api_key
                      ? 'Step 1: Enter your Kite Connect API credentials below'
                      : !status?.zerodha.has_access_token
                        ? 'Step 2: Click Login and complete the Zerodha authentication'
                        : status?.zerodha.error || 'Access token expired — login again'}
                  </div>
                </div>
              </div>
            )}

            {/* Step 1: API credentials */}
            <div className="space-y-2">
              <label className="text-xs font-medium text-primary">API Key</label>
              <Input
                value={kiteApiKey}
                onChange={(e) => setKiteApiKey(e.target.value)}
                placeholder="Your Kite Connect API key"
                className="text-sm font-mono"
              />
              <label className="text-xs font-medium text-primary">API Secret</label>
              <Input
                type="password"
                value={kiteApiSecret}
                onChange={(e) => setKiteApiSecret(e.target.value)}
                placeholder="Your Kite Connect API secret"
                className="text-sm font-mono"
              />
              <Button
                size="sm"
                onClick={handleSaveKiteCredentials}
                disabled={kiteLoginLoading || !kiteApiKey.trim() || !kiteApiSecret.trim()}
                className="gap-2"
              >
                {kiteLoginLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Save Credentials
              </Button>
            </div>

            {/* Step 2: Login */}
            {(status?.zerodha.has_api_key || kiteLoginUrl) && (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm" onClick={handleOpenKiteLogin} className="gap-2">
                    <LogIn className="h-3 w-3" /> Login to Zerodha
                    <ExternalLink className="h-3 w-3" />
                  </Button>
                  <span className="text-[10px] text-muted-foreground">Opens Zerodha login in new tab</span>
                </div>
              </div>
            )}

            {/* Step 3: Enter request token from redirect URL */}
            {status?.zerodha.has_api_key && !zerodhaConnected && (
              <div className="space-y-2">
                <label className="text-xs font-medium text-primary">Request Token</label>
                <p className="text-[10px] text-muted-foreground">
                  After logging in, you'll be redirected. Copy the <code className="bg-muted px-1 rounded">request_token</code> from the redirect URL and paste it here.
                </p>
                <div className="flex gap-2">
                  <Input
                    value={requestToken}
                    onChange={(e) => setRequestToken(e.target.value)}
                    placeholder="Paste request_token from redirect URL"
                    className="flex-1 text-sm font-mono"
                  />
                  <Button
                    size="sm"
                    onClick={handleExchangeToken}
                    disabled={kiteTokenLoading || !requestToken.trim()}
                    className="gap-2"
                  >
                    {kiteTokenLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                    Connect
                  </Button>
                </div>
              </div>
            )}

            {/* Test connection */}
            <div className="flex items-center gap-3 pt-1">
              <Button variant="outline" size="sm" onClick={handleTestZerodha} disabled={testingZerodha} className="gap-2">
                {testingZerodha ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                Test Connection
              </Button>
              {zerodhaTestResult && (
                <span className={`text-xs ${zerodhaTestResult.ok ? 'text-emerald-500' : 'text-red-400'}`}>
                  {zerodhaTestResult.msg}
                </span>
              )}
            </div>

            {/* Setup guide */}
            <div className="text-xs text-muted-foreground space-y-1.5 pt-2 border-t border-border/50">
              <p className="font-medium text-primary text-[11px]">How to get your API credentials:</p>
              <ol className="list-decimal list-inside space-y-1 text-[10px]">
                <li>Go to <a href="https://developers.kite.trade" target="_blank" rel="noopener" className="text-blue-500 hover:underline">developers.kite.trade</a> and create a free Kite Connect app</li>
                <li>Copy the <strong>API Key</strong> and <strong>API Secret</strong> from your app dashboard</li>
                <li>Paste them above and click Save Credentials</li>
                <li>Click Login — you'll be taken to Zerodha to authenticate with 2FA</li>
                <li>After login, you'll be redirected — copy the <code className="bg-muted px-0.5 rounded">request_token</code> from the URL</li>
                <li>Paste the token and click Connect — this generates your daily access token</li>
              </ol>
              <p className="text-[10px] pt-1">
                The access token expires daily. You'll need to repeat steps 4–6 each morning.
                Portfolio data, holdings, positions, funds, and order placement all work through Kite Connect.
              </p>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ── Trading Mode ───────────────────────────────────────── */}
      <Card className="bg-panel border-gray-700">
        <SectionToggle
          title="Trading Mode"
          icon={ArrowRightLeft}
          open={openSections.trading}
          onToggle={() => toggleSection('trading')}
          badge={
            <Badge variant={mode === 'live' ? 'warning' : 'success'} className="text-[11px]">
              {mode.toUpperCase()}
            </Badge>
          }
        />
        {openSections.trading && (
          <CardContent className="px-4 pb-4 space-y-4">
            <p className="text-xs text-muted-foreground">
              Switch between paper trading (simulated) and live trading (real orders via Zerodha).
            </p>

            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => handleModeSwitch('paper')}
                className={`flex flex-col items-center gap-2 p-4 rounded-lg border transition-all ${
                  mode === 'paper'
                    ? 'border-blue-500 bg-blue-500/10 text-blue-500'
                    : 'border-gray-600 hover:border-gray-500 text-muted-foreground hover:text-primary'
                }`}
              >
                <Shield className="h-6 w-6" />
                <span className="text-sm font-medium">Paper Trading</span>
                <span className="text-[10px] text-center">Simulated orders, no real money</span>
              </button>
              <button
                onClick={() => handleModeSwitch('live')}
                className={`flex flex-col items-center gap-2 p-4 rounded-lg border transition-all ${
                  mode === 'live'
                    ? 'border-amber-500 bg-amber-500/10 text-amber-500'
                    : 'border-gray-600 hover:border-gray-500 text-muted-foreground hover:text-primary'
                }`}
              >
                <Zap className="h-6 w-6" />
                <span className="text-sm font-medium">Live Trading</span>
                <span className="text-[10px] text-center">Real orders via Zerodha</span>
              </button>
            </div>

            {mode === 'live' && (
              <Card className="bg-amber-500/5 border-amber-500/20">
                <CardContent className="p-3 flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-500">
                    Live trading is active. Real money is at risk. Ensure your risk parameters are
                    properly configured before starting the trader.
                  </p>
                </CardContent>
              </Card>
            )}

            <div className="flex items-center justify-between py-2">
              <div>
                <div className="text-sm font-medium text-primary">Auto Trade</div>
                <div className="text-xs text-muted-foreground">Execute trades automatically without manual confirmation</div>
              </div>
              <button
                onClick={() => handleSaveTradingConfig({ auto_trade: !(status?.trading.auto_trade ?? false) })}
                className={`relative w-11 h-6 rounded-full transition-colors ${
                  status?.trading.auto_trade ? 'bg-blue-500' : 'bg-gray-600'
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                    status?.trading.auto_trade ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ── Risk Management ────────────────────────────────────── */}
      <Card className="bg-panel border-gray-700">
        <SectionToggle
          title="Risk Management"
          icon={Shield}
          open={openSections.risk}
          onToggle={() => toggleSection('risk')}
        />
        {openSections.risk && (
          <CardContent className="px-4 pb-4 space-y-4">
            <p className="text-xs text-muted-foreground">
              Configure guardrails to limit exposure, losses, and position sizing.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <RiskField
                label="Max Position %"
                description="Maximum portfolio allocation per stock"
                value={riskForm.max_position_pct}
                onChange={(v) => setRiskForm((p) => ({ ...p, max_position_pct: v }))}
                suffix="%"
                multiplier={100}
              />
              <RiskField
                label="Max Portfolio Exposure"
                description="Maximum total capital deployed"
                value={riskForm.max_portfolio_exposure}
                onChange={(v) => setRiskForm((p) => ({ ...p, max_portfolio_exposure: v }))}
                suffix="%"
                multiplier={100}
              />
              <RiskField
                label="Max Order Value"
                description="Maximum value per single order"
                value={riskForm.max_single_order_value}
                onChange={(v) => setRiskForm((p) => ({ ...p, max_single_order_value: v }))}
                prefix="₹"
                multiplier={1}
              />
              <RiskField
                label="Max Daily Loss"
                description="Stop trading after this daily drawdown"
                value={riskForm.max_daily_loss_pct}
                onChange={(v) => setRiskForm((p) => ({ ...p, max_daily_loss_pct: v }))}
                suffix="%"
                multiplier={100}
              />
              <RiskField
                label="Max Open Positions"
                description="Maximum simultaneous open positions"
                value={riskForm.max_open_positions}
                onChange={(v) => setRiskForm((p) => ({ ...p, max_open_positions: v }))}
                multiplier={1}
                isInt
              />
              <RiskField
                label="Stop Loss"
                description="Trailing stop loss percentage"
                value={riskForm.stop_loss_pct}
                onChange={(v) => setRiskForm((p) => ({ ...p, stop_loss_pct: v }))}
                suffix="%"
                multiplier={100}
              />
              <RiskField
                label="Take Profit"
                description="Target profit percentage"
                value={riskForm.take_profit_pct}
                onChange={(v) => setRiskForm((p) => ({ ...p, take_profit_pct: v }))}
                suffix="%"
                multiplier={100}
              />
            </div>

            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={() => handleSaveTradingConfig(riskForm)}
                disabled={saving}
                className="gap-2"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Save Risk Config
              </Button>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ── Scheduler & Analysis ───────────────────────────────── */}
      <Card className="bg-panel border-gray-700">
        <SectionToggle
          title="Scheduler & Analysis"
          icon={Clock}
          open={openSections.scheduler}
          onToggle={() => toggleSection('scheduler')}
        />
        {openSections.scheduler && (
          <CardContent className="px-4 pb-4 space-y-4">
            <p className="text-xs text-muted-foreground">
              Configure analysis frequency and market timing.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-primary">Market Open (IST)</label>
                <Input value={status?.scheduler.market_open ?? '09:15'} disabled className="text-sm" />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-primary">Market Close (IST)</label>
                <Input value={status?.scheduler.market_close ?? '15:30'} disabled className="text-sm" />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-primary">Analysis Interval (minutes)</label>
                <Input
                  type="number"
                  min={1}
                  max={120}
                  value={schedulerForm.analysis_interval_minutes}
                  onChange={(e) => setSchedulerForm({ analysis_interval_minutes: parseInt(e.target.value) || 5 })}
                  className="text-sm"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-primary">IST Time Now</label>
                <Input value={status?.current_time_ist ?? ''} disabled className="text-sm" />
              </div>
            </div>

            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={() => handleSaveTradingConfig(schedulerForm)}
                disabled={saving}
                className="gap-2"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Save Scheduler
              </Button>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ── Model Configuration ────────────────────────────────── */}
      <Card className="bg-panel border-gray-700">
        <SectionToggle
          title="AI Model"
          icon={Bot}
          open={openSections.model}
          onToggle={() => toggleSection('model')}
          badge={
            <Badge variant="secondary" className="text-[11px]">
              {status?.model.name?.split('-').slice(0, 3).join('-') ?? 'N/A'}
            </Badge>
          }
        />
        {openSections.model && (
          <CardContent className="px-4 pb-4 space-y-4">
            <p className="text-xs text-muted-foreground">
              Set the default LLM model used for analysis and trading decisions.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-primary">Model Name</label>
                <Input
                  value={modelForm.model_name}
                  onChange={(e) => setModelForm((p) => ({ ...p, model_name: e.target.value }))}
                  placeholder="claude-opus-4-6"
                  className="text-sm"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-primary">Provider</label>
                <select
                  value={modelForm.model_provider}
                  onChange={(e) => setModelForm((p) => ({ ...p, model_provider: e.target.value }))}
                  className="w-full h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="Anthropic">Anthropic</option>
                  <option value="OpenAI">OpenAI</option>
                  <option value="Google">Google</option>
                  <option value="DeepSeek">DeepSeek</option>
                  <option value="Groq">Groq</option>
                  <option value="OpenRouter">OpenRouter</option>
                </select>
              </div>
            </div>

            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={() => handleSaveTradingConfig(modelForm)}
                disabled={saving}
                className="gap-2"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Save Model
              </Button>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ── API Key Status Overview ────────────────────────────── */}
      <Card className="bg-panel border-gray-700">
        <SectionToggle
          title="API Key Status"
          icon={Globe}
          open={openSections.apiStatus}
          onToggle={() => toggleSection('apiStatus')}
          badge={
            <Badge variant="secondary" className="text-[11px]">
              {activeKeys.length} connected
            </Badge>
          }
        />
        {openSections.apiStatus && (
          <CardContent className="px-4 pb-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Overview of all configured API keys. Manage keys in the API Keys section.
            </p>

            {status?.api_keys && status.api_keys.length > 0 ? (
              <div className="space-y-2">
                {status.api_keys.map((k) => (
                  <div
                    key={k.provider}
                    className="flex items-center justify-between py-2 px-3 rounded-lg bg-muted/30"
                  >
                    <div className="flex items-center gap-3">
                      <span className={`w-2 h-2 rounded-full ${k.is_active && k.has_key ? 'bg-emerald-500' : 'bg-gray-500'}`} />
                      <span className="text-sm text-primary">
                        {k.provider.replace(/_/g, ' ').replace('API KEY', '').trim()}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {k.last_used && (
                        <span className="text-[10px] text-muted-foreground">
                          Last used {new Date(k.last_used).toLocaleDateString()}
                        </span>
                      )}
                      <StatusBadge
                        ok={k.is_active && k.has_key}
                        label={k.is_active && k.has_key ? 'Active' : k.has_key ? 'Inactive' : 'Missing'}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-6 text-sm text-muted-foreground">
                No API keys configured. Add keys in the API Keys section.
              </div>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
}

function RiskField({
  label,
  description,
  value,
  onChange,
  prefix,
  suffix,
  multiplier = 1,
  isInt = false,
}: {
  label: string;
  description: string;
  value: number;
  onChange: (v: number) => void;
  prefix?: string;
  suffix?: string;
  multiplier?: number;
  isInt?: boolean;
}) {
  const displayValue = multiplier !== 1 ? (value * multiplier).toFixed(isInt ? 0 : 1) : value.toString();

  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-primary">{label}</label>
      <p className="text-[10px] text-muted-foreground">{description}</p>
      <div className="relative">
        {prefix && (
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
            {prefix}
          </span>
        )}
        <Input
          type="number"
          value={displayValue}
          onChange={(e) => {
            const raw = parseFloat(e.target.value) || 0;
            onChange(multiplier !== 1 ? raw / multiplier : isInt ? Math.round(raw) : raw);
          }}
          className={`text-sm ${prefix ? 'pl-7' : ''} ${suffix ? 'pr-7' : ''}`}
          step={isInt ? 1 : 0.1}
        />
        {suffix && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}
