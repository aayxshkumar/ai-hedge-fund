import { Accordion } from '@/components/ui/accordion';
import { ComponentGroup } from '@/data/sidebar-components';
import { SearchBox } from '../search-box';
import { ComponentItemGroup } from './component-item-group';

interface ComponentListProps {
  componentGroups: ComponentGroup[];
  searchQuery: string;
  isLoading: boolean;
  openGroups: string[];
  filteredGroups: ComponentGroup[];
  activeItem: string | null;
  onSearchChange: (query: string) => void;
  onAccordionChange: (value: string[]) => void;
  onRetry?: () => void;
}

export function ComponentList({
  componentGroups,
  searchQuery,
  isLoading,
  openGroups,
  filteredGroups,
  activeItem,
  onSearchChange,
  onAccordionChange,
  onRetry,
}: ComponentListProps) {
  return (
    <div className="flex-grow overflow-auto text-primary scrollbar-thin scrollbar-thumb-ramp-grey-700">
      <SearchBox 
        value={searchQuery} 
        onChange={onSearchChange}
        placeholder="Search components..."
      />
      
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="text-muted-foreground text-sm">Loading components...</div>
        </div>
      ) : (
        <Accordion 
          type="multiple" 
          className="w-full" 
          value={openGroups} 
          onValueChange={onAccordionChange}
        >
          {filteredGroups.map(group => (
            <ComponentItemGroup
              key={group.name} 
              group={group}
              activeItem={activeItem}
            />
          ))}
        </Accordion>
      )}

      {!isLoading && filteredGroups.length === 0 && (
        <div className="text-center py-8 text-muted-foreground text-sm">
          {componentGroups.length === 0 ? (
            <div className="space-y-2">
              <div>No components available</div>
              <div className="text-xs">Ensure the backend server is running on port 8000</div>
              {onRetry && (
                <button onClick={onRetry} className="mt-2 px-3 py-1 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer">
                  Retry
                </button>
              )}
            </div>
          ) : (
            'No components match your search'
          )}
        </div>
      )}
    </div>
  );
} 