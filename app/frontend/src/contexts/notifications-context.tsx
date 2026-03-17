import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from 'react';

export interface AppNotification {
  id: string;
  type: 'review' | 'penny_scan' | 'daily_analysis' | 'rebalance' | 'trade' | 'info';
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  data?: Record<string, any>;
}

interface NotificationsContextType {
  notifications: AppNotification[];
  unreadCount: number;
  addNotification: (n: Omit<AppNotification, 'id' | 'timestamp' | 'read'>) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  clearAll: () => void;
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
}

const NotificationsContext = createContext<NotificationsContextType | null>(null);

export function useNotifications() {
  const ctx = useContext(NotificationsContext);
  if (!ctx) throw new Error('useNotifications must be used within NotificationsProvider');
  return ctx;
}

const STORAGE_KEY = 'ai-hedge-fund-notifications';
const MAX_NOTIFICATIONS = 50;

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<AppNotification[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [panelOpen, setPanelOpen] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications.slice(0, MAX_NOTIFICATIONS)));
    } catch {}
  }, [notifications]);

  const addNotification = useCallback((n: Omit<AppNotification, 'id' | 'timestamp' | 'read'>) => {
    const notification: AppNotification = {
      ...n,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      timestamp: new Date().toISOString(),
      read: false,
    };
    setNotifications(prev => [notification, ...prev].slice(0, MAX_NOTIFICATIONS));
  }, []);

  const markRead = useCallback((id: string) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  const unreadCount = notifications.filter(n => !n.read).length;

  return (
    <NotificationsContext.Provider value={{
      notifications, unreadCount, addNotification,
      markRead, markAllRead, clearAll,
      panelOpen, setPanelOpen,
    }}>
      {children}
    </NotificationsContext.Provider>
  );
}
