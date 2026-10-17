import { useTabsContext } from '@/contexts/tabs-context';
import { cn } from '@/lib/utils';
import { TabService } from '@/services/tab-service';
import { FileText, FolderOpen } from 'lucide-react';
import { useEffect } from 'react';

interface TabContentProps {
  className?: string;
}

export function TabContent({ className }: TabContentProps) {
  const { tabs, activeTabId, openTab } = useTabsContext();

  const activeTab = tabs.find(tab => tab.id === activeTabId);

  // Restore content for tabs that don't have it (from localStorage restoration)
  useEffect(() => {
    if (activeTab && !activeTab.content) {
      try {
        const restoredTab = TabService.restoreTab({
          type: activeTab.type,
          title: activeTab.title,
          flow: activeTab.flow,
          metadata: activeTab.metadata,
        });
        
        // Update the tab with restored content
        openTab({
          id: activeTab.id,
          type: restoredTab.type,
          title: restoredTab.title,
          content: restoredTab.content,
          flow: restoredTab.flow,
          metadata: restoredTab.metadata,
        });
      } catch (error) {
        console.error('Failed to restore tab content:', error);
      }
    }
  }, [activeTab, openTab]);

  if (!activeTab) {
    return (
      <div className={cn(
        "h-full w-full flex items-center justify-center bg-background text-muted-foreground",
        className
      )}>
        <div className="text-center space-y-5 max-w-lg px-6">
          <FolderOpen size={48} className="mx-auto text-muted-foreground/50" />
          <div>
            <div className="text-xl font-medium mb-2 text-foreground">Welcome to the AI Hedge Fund</div>
            <div className="text-sm">Your Zerodha stocks and mutual funds, analysed by a multi-agent research desk.</div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-left">
            {[
              { title: 'Portfolio', desc: 'Holdings, technicals and the AI analyst review', open: () => openTab(TabService.createPortfolioTab()) },
              { title: 'Mutual Funds', desc: 'Allocation, overlap and a construction review', open: () => openTab(TabService.createMutualFundsTab()) },
              { title: 'Stock Analysis', desc: 'Deep-dive any NSE/BSE stock with 21 analysts', open: () => openTab(TabService.createStockAnalysisTab()) },
            ].map(c => (
              <button key={c.title} onClick={c.open} className="rounded-lg border border-border/60 bg-card/50 hover:bg-accent/30 hover:border-primary/40 transition-colors p-3 cursor-pointer">
                <div className="text-sm font-medium text-foreground">{c.title}</div>
                <div className="text-[11px] text-muted-foreground mt-0.5 leading-snug">{c.desc}</div>
              </button>
            ))}
          </div>
          <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground/70">
            <FileText size={14} />
            <span>Flows from the left sidebar (⌘B) open here too</span>
          </div>
        </div>
      </div>
    );
  }

  // Show loading state if content is being restored
  if (!activeTab.content) {
    return (
      <div className={cn(
        "h-full w-full flex items-center justify-center bg-background text-muted-foreground",
        className
      )}>
        <div className="text-center">
          <div className="text-lg font-medium mb-2">Loading {activeTab.title}...</div>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("h-full w-full bg-background overflow-hidden", className)}>
      {activeTab.content}
    </div>
  );
} 