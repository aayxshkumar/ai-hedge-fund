import { Settings } from '@/components/settings/settings';
import { FlowTabContent } from '@/components/tabs/flow-tab-content';
import { StockAnalysis } from '@/components/stock-analysis/stock-analysis';
import { Portfolio } from '@/components/portfolio/portfolio';
import { MutualFunds } from '@/components/mutual-funds/mutual-funds';
import { Tradebook } from '@/components/tradebook/tradebook';
import { Flow } from '@/types/flow';
import { ReactNode, createElement } from 'react';

export interface TabData {
  type: 'flow' | 'settings' | 'stock-analysis' | 'portfolio' | 'mutual-funds' | 'tradebook';
  title: string;
  flow?: Flow;
  metadata?: Record<string, any>;
}

export class TabService {
  static createTabContent(tabData: TabData): ReactNode {
    switch (tabData.type) {
      case 'flow':
        if (!tabData.flow) {
          throw new Error('Flow tab requires flow data');
        }
        return createElement(FlowTabContent, { flow: tabData.flow });
      
      case 'settings':
        return createElement(Settings);

      case 'stock-analysis':
        return createElement(StockAnalysis);

      case 'portfolio':
        return createElement(Portfolio);

      case 'mutual-funds':
        return createElement(MutualFunds);

      case 'tradebook':
        return createElement(Tradebook);

      default:
        throw new Error(`Unsupported tab type: ${tabData.type}`);
    }
  }

  static createFlowTab(flow: Flow): TabData & { content: ReactNode } {
    return {
      type: 'flow',
      title: flow.name,
      flow: flow,
      content: TabService.createTabContent({ type: 'flow', title: flow.name, flow }),
    };
  }

  static createSettingsTab(): TabData & { content: ReactNode } {
    return {
      type: 'settings',
      title: 'Settings',
      content: TabService.createTabContent({ type: 'settings', title: 'Settings' }),
    };
  }

  static createStockAnalysisTab(): TabData & { content: ReactNode } {
    return {
      type: 'stock-analysis',
      title: 'Stock Analysis',
      content: TabService.createTabContent({ type: 'stock-analysis', title: 'Stock Analysis' }),
    };
  }

  static createPortfolioTab(): TabData & { content: ReactNode } {
    return {
      type: 'portfolio',
      title: 'Portfolio',
      content: TabService.createTabContent({ type: 'portfolio', title: 'Portfolio' }),
    };
  }

  static createMutualFundsTab(): TabData & { content: ReactNode } {
    return {
      type: 'mutual-funds',
      title: 'Mutual Funds',
      content: TabService.createTabContent({ type: 'mutual-funds', title: 'Mutual Funds' }),
    };
  }

  static createTradebookTab(): TabData & { content: ReactNode } {
    return {
      type: 'tradebook',
      title: 'Tradebook',
      content: TabService.createTabContent({ type: 'tradebook', title: 'Tradebook' }),
    };
  }

  // Restore tab content for persisted tabs (used when loading from localStorage)
  static restoreTabContent(tabData: TabData): ReactNode {
    return TabService.createTabContent(tabData);
  }

  // Helper method to restore a complete tab from saved data
  static restoreTab(savedTab: TabData): TabData & { content: ReactNode } {
    switch (savedTab.type) {
      case 'flow':
        if (!savedTab.flow) {
          throw new Error('Flow tab requires flow data for restoration');
        }
        return TabService.createFlowTab(savedTab.flow);
      
      case 'settings':
        return TabService.createSettingsTab();

      case 'stock-analysis':
        return TabService.createStockAnalysisTab();

      case 'portfolio':
        return TabService.createPortfolioTab();

      case 'mutual-funds':
        return TabService.createMutualFundsTab();

      case 'tradebook':
        return TabService.createTradebookTab();

      default:
        throw new Error(`Cannot restore unsupported tab type: ${savedTab.type}`);
    }
  }
} 