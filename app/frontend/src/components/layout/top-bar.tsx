import { Button } from '@/components/ui/button';
import {
  BookOpen, Bot, Briefcase, FlaskConical, Landmark, Settings, TrendingUp,
} from 'lucide-react';

interface TopBarProps {
  onSettingsClick: () => void;
  onStrategyLabClick?: () => void;
  onStockAnalysisClick?: () => void;
  onDerivativesLabClick?: () => void;
  onAlgoDashboardClick?: () => void;
  onPortfolioClick?: () => void;
  onTradebookClick?: () => void;
}

export function TopBar({
  onSettingsClick,
  onStrategyLabClick,
  onStockAnalysisClick,
  onDerivativesLabClick,
  onAlgoDashboardClick,
  onPortfolioClick,
  onTradebookClick,
}: TopBarProps) {
  return (
    <div className="absolute top-0 right-0 z-40 flex items-center gap-0.5 py-1 px-2 bg-panel/80 backdrop-blur-sm rounded-bl-lg">
      {onPortfolioClick && (
        <button
          onClick={onPortfolioClick}
          className="flex items-center gap-1.5 h-7 px-2.5 text-[11px] font-medium rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer"
          title="My Portfolio"
        >
          <Briefcase size={13} />
          <span className="hidden lg:inline">Portfolio</span>
        </button>
      )}

      {onStockAnalysisClick && (
        <button
          onClick={onStockAnalysisClick}
          className="flex items-center gap-1.5 h-7 px-2.5 text-[11px] font-medium rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer"
          title="AI Stock Analysis"
        >
          <TrendingUp size={13} />
          <span className="hidden lg:inline">Analysis</span>
        </button>
      )}

      {onStrategyLabClick && (
        <button
          onClick={onStrategyLabClick}
          className="flex items-center gap-1.5 h-7 px-2.5 text-[11px] font-medium rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer"
          title="Stock Strategy Backtesting"
        >
          <FlaskConical size={13} />
          <span className="hidden lg:inline">Stocks</span>
        </button>
      )}

      {onDerivativesLabClick && (
        <button
          onClick={onDerivativesLabClick}
          className="flex items-center gap-1.5 h-7 px-2.5 text-[11px] font-medium rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer"
          title="Options & Futures Backtesting"
        >
          <Landmark size={13} />
          <span className="hidden lg:inline">F&O</span>
        </button>
      )}

      {onAlgoDashboardClick && (
        <button
          onClick={onAlgoDashboardClick}
          className="flex items-center gap-1.5 h-7 px-2.5 text-[11px] font-medium rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer"
          title="Automatic Algo Trading Dashboard"
        >
          <Bot size={13} />
          <span className="hidden lg:inline">Auto Trade</span>
        </button>
      )}

      {onTradebookClick && (
        <button
          onClick={onTradebookClick}
          className="flex items-center gap-1.5 h-7 px-2.5 text-[11px] font-medium rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors cursor-pointer"
          title="Trade Journal — All trades logged for model learning"
        >
          <BookOpen size={13} />
          <span className="hidden lg:inline">Tradebook</span>
        </button>
      )}

      <div className="w-px h-4 bg-border mx-1" />

      <Button
        variant="ghost"
        size="sm"
        onClick={onSettingsClick}
        className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground transition-colors"
        title="Settings (⌘,)"
      >
        <Settings size={14} />
      </Button>
    </div>
  );
}
