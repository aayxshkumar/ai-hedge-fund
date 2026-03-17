import { useNotifications, AppNotification } from '@/contexts/notifications-context';
import { cn } from '@/lib/utils';
import {
  ArrowRightLeft,
  Bell,
  Bot,
  CheckCheck,
  BarChart3,
  Search,
  Trash2,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react';

const TYPE_CONFIG: Record<AppNotification['type'], { icon: typeof Bot; color: string }> = {
  review: { icon: Bot, color: 'text-blue-400' },
  penny_scan: { icon: Search, color: 'text-purple-400' },
  daily_analysis: { icon: BarChart3, color: 'text-cyan-400' },
  rebalance: { icon: TrendingUp, color: 'text-amber-400' },
  trade: { icon: Zap, color: 'text-emerald-400' },
  info: { icon: Bell, color: 'text-zinc-400' },
};

const ACTION_COLOR: Record<string, string> = {
  strong_buy: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  buy: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  hold: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/20',
  sell: 'bg-red-500/15 text-red-400 border-red-500/20',
  strong_sell: 'bg-red-500/20 text-red-400 border-red-500/30',
};

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function NotificationBell() {
  const { unreadCount, panelOpen, setPanelOpen } = useNotifications();

  return (
    <button
      onClick={() => setPanelOpen(!panelOpen)}
      title="Notifications"
      className={cn(
        'relative w-10 h-10 flex items-center justify-center rounded-md transition-colors cursor-pointer',
        panelOpen ? 'text-primary bg-primary/10' : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
      )}
    >
      <Bell size={18} />
      {unreadCount > 0 && (
        <span className="absolute top-1 right-1 min-w-[16px] h-4 flex items-center justify-center px-1 text-[9px] font-bold rounded-full bg-red-500 text-white">
          {unreadCount > 9 ? '9+' : unreadCount}
        </span>
      )}
    </button>
  );
}

export function NotificationPanel() {
  const { notifications, panelOpen, setPanelOpen, markRead, markAllRead, clearAll } = useNotifications();

  if (!panelOpen) return null;

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={() => setPanelOpen(false)} />

      <div className="fixed top-0 right-0 bottom-0 w-80 z-50 bg-panel border-l border-border shadow-2xl flex flex-col animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Bell size={16} className="text-primary" />
            <span className="text-sm font-semibold">Notifications</span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={markAllRead} title="Mark all read" className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer">
              <CheckCheck size={14} />
            </button>
            <button onClick={clearAll} title="Clear all" className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer">
              <Trash2 size={14} />
            </button>
            <button onClick={() => setPanelOpen(false)} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer">
              <X size={14} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-48 text-muted-foreground">
              <Bell size={24} className="mb-2 opacity-40" />
              <span className="text-xs">No notifications yet</span>
            </div>
          ) : (
            notifications.map(n => {
              const isFlip = n.data?.type === 'signal_flip';
              const cfg = isFlip
                ? { icon: ArrowRightLeft, color: 'text-amber-400' }
                : (TYPE_CONFIG[n.type] || TYPE_CONFIG.info);
              const Icon = cfg.icon;
              return (
                <button
                  key={n.id}
                  onClick={() => markRead(n.id)}
                  className={cn(
                    'w-full text-left px-4 py-3 border-b border-border/50 hover:bg-muted/30 transition-colors cursor-pointer',
                    !n.read && 'bg-primary/5',
                  )}
                >
                  <div className="flex gap-3">
                    <div className={cn('mt-0.5 shrink-0', cfg.color)}>
                      <Icon size={16} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={cn('text-xs font-medium truncate', !n.read ? 'text-foreground' : 'text-muted-foreground')}>
                          {n.title}
                        </span>
                        {!n.read && <div className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />}
                      </div>
                      {isFlip && n.data ? (
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className={cn('text-[10px] px-1.5 py-0.5 rounded border font-medium', ACTION_COLOR[n.data.from] || ACTION_COLOR.hold)}>
                            {(n.data.from || '').replace('_', ' ')}
                          </span>
                          <span className="text-[10px] text-zinc-500">→</span>
                          <span className={cn('text-[10px] px-1.5 py-0.5 rounded border font-medium', ACTION_COLOR[n.data.to] || ACTION_COLOR.hold)}>
                            {(n.data.to || '').replace('_', ' ')}
                          </span>
                        </div>
                      ) : (
                        <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">{n.message}</p>
                      )}
                      <span className="text-[10px] text-zinc-500 mt-1 block">{timeAgo(n.timestamp)}</span>
                    </div>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}
