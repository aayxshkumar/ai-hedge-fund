import { TabBar } from '@/components/tabs/tab-bar';
import { TabContent } from '@/components/tabs/tab-content';
import { SidebarProvider } from '@/components/ui/sidebar';
import { FlowProvider } from '@/contexts/flow-context';
import { LayoutProvider } from '@/contexts/layout-context';
import { NotificationsProvider } from '@/contexts/notifications-context';
import { TabsProvider, useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { ReactFlowProvider } from '@xyflow/react';
import { useEffect, useRef } from 'react';
import { ErrorBoundary } from './error-boundary';
import { SideNav } from './layout/side-nav';
import { NotificationPanel } from './layout/notification-panel';

function LayoutContent() {
  const { openTab, tabs } = useTabsContext();
  const initialized = useRef(false);

  useEffect(() => {
    if (!initialized.current && tabs.length === 0) {
      initialized.current = true;
      openTab(TabService.createStockAnalysisTab());
    }
  }, [tabs.length, openTab]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <SideNav />

      <div className="flex-1 flex flex-col min-w-0">
        <div className="shrink-0 z-10">
          <TabBar />
        </div>

        <main className="flex-1 overflow-hidden">
          <ErrorBoundary>
            <TabContent className="h-full w-full" />
          </ErrorBoundary>
        </main>
      </div>

      <NotificationPanel />
    </div>
  );
}

export function Layout() {
  return (
    <SidebarProvider defaultOpen={true}>
      <ReactFlowProvider>
        <FlowProvider>
          <TabsProvider>
            <NotificationsProvider>
              <LayoutProvider>
                <LayoutContent />
              </LayoutProvider>
            </NotificationsProvider>
          </TabsProvider>
        </FlowProvider>
      </ReactFlowProvider>
    </SidebarProvider>
  );
}
