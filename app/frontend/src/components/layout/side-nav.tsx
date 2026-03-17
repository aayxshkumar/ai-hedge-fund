import { useTabsContext, TabType } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { cn } from '@/lib/utils';
import {
  BookOpen,
  Bot,
  Briefcase,
  FlaskConical,
  Landmark,
  Settings,
  TrendingUp,
} from 'lucide-react';
import { ReactNode } from 'react';
import { NotificationBell } from './notification-panel';

interface NavItem {
  type: TabType;
  icon: ReactNode;
  label: string;
  title: string;
  create: () => ReturnType<typeof TabService.createPortfolioTab>;
}

const NAV_ITEMS: NavItem[] = [
  { type: 'portfolio', icon: <Briefcase size={18} />, label: 'Portfolio', title: 'My Portfolio', create: () => TabService.createPortfolioTab() },
  { type: 'stock-analysis', icon: <TrendingUp size={18} />, label: 'Analysis', title: 'AI Stock Analysis', create: () => TabService.createStockAnalysisTab() },
  { type: 'strategy-lab', icon: <FlaskConical size={18} />, label: 'Stocks', title: 'Stock Strategy Backtesting', create: () => TabService.createStrategyLabTab() },
  { type: 'derivatives-lab', icon: <Landmark size={18} />, label: 'F&O', title: 'Options & Futures', create: () => TabService.createDerivativesLabTab() },
  { type: 'algo-dashboard', icon: <Bot size={18} />, label: 'Auto Trade', title: 'Algo Trading Dashboard', create: () => TabService.createAlgoDashboardTab() },
  { type: 'tradebook', icon: <BookOpen size={18} />, label: 'Tradebook', title: 'Trade Journal', create: () => TabService.createTradebookTab() },
];

export function SideNav() {
  const { openTab, tabs, activeTabId } = useTabsContext();

  const isActive = (type: TabType) => {
    const activeTab = tabs.find(t => t.id === activeTabId);
    return activeTab?.type === type;
  };

  const isOpen = (type: TabType) => tabs.some(t => t.type === type);

  return (
    <div className="flex flex-col h-full w-12 bg-panel border-r border-border shrink-0">
      <div className="flex-1 flex flex-col items-center pt-2 gap-0.5">
        {NAV_ITEMS.map(item => (
          <button
            key={item.type}
            onClick={() => openTab(item.create())}
            title={item.title}
            className={cn(
              'relative w-10 h-10 flex items-center justify-center rounded-md transition-colors cursor-pointer',
              isActive(item.type)
                ? 'text-primary bg-primary/10'
                : isOpen(item.type)
                  ? 'text-primary/70 hover:bg-accent/60 hover:text-primary'
                  : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
            )}
          >
            {isActive(item.type) && (
              <div className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-r bg-primary" />
            )}
            {isOpen(item.type) && !isActive(item.type) && (
              <div className="absolute left-0 top-3 bottom-3 w-0.5 rounded-r bg-primary/40" />
            )}
            {item.icon}
          </button>
        ))}
      </div>

      <div className="flex flex-col items-center pb-2 gap-0.5">
        <NotificationBell />
        <button
          onClick={() => openTab(TabService.createSettingsTab())}
          title="Settings"
          className={cn(
            'w-10 h-10 flex items-center justify-center rounded-md transition-colors cursor-pointer',
            tabs.find(t => t.id === activeTabId)?.type === 'settings'
              ? 'text-primary bg-primary/10'
              : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
          )}
        >
          <Settings size={18} />
        </button>
      </div>
    </div>
  );
}
