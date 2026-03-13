import * as React from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { restrictToWindowEdges } from "@dnd-kit/modifiers";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Slot } from "@radix-ui/react-slot";

type KanbanRecord<T> = Record<string, T[]>;

type KanbanContextValue<T> = {
  value: KanbanRecord<T>;
  getItemValue: (item: T) => string;
  activeItemId: string | null;
  activeColumn: string | null;
};

const KanbanContext = React.createContext<KanbanContextValue<unknown> | null>(null);

function useKanbanContext<T>(consumer: string): KanbanContextValue<T> {
  const context = React.useContext(KanbanContext);
  if (!context) {
    throw new Error(`${consumer} must be used inside Kanban`);
  }
  return context as KanbanContextValue<T>;
}

function findContainerByItemId<T>(columns: KanbanRecord<T>, getItemValue: (item: T) => string, itemId: string): string | null {
  for (const [columnId, items] of Object.entries(columns)) {
    if (items.some((item) => getItemValue(item) === itemId)) {
      return columnId;
    }
  }
  return null;
}

type MoveMeta = {
  itemId: string;
  fromColumn: string;
  toColumn: string;
};

type KanbanProps<T> = {
  value: KanbanRecord<T>;
  onValueChange: (next: KanbanRecord<T>) => void;
  getItemValue: (item: T) => string;
  onItemMove?: (meta: MoveMeta) => void;
  onDragStartItem?: (itemId: string) => void;
  onDragEndItem?: () => void;
  children: React.ReactNode;
};

export function Kanban<T>({
  value,
  onValueChange,
  getItemValue,
  onItemMove,
  onDragStartItem,
  onDragEndItem,
  children,
}: KanbanProps<T>): JSX.Element {
  const [activeItemId, setActiveItemId] = React.useState<string | null>(null);
  const [activeColumn, setActiveColumn] = React.useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const onDragStart = React.useCallback((event: DragStartEvent) => {
    const id = String(event.active.id);
    setActiveItemId(id);
    setActiveColumn(findContainerByItemId(value, getItemValue, id));
    onDragStartItem?.(id);
  }, [getItemValue, onDragStartItem, value]);

  const onDragEnd = React.useCallback((event: DragEndEvent) => {
    const activeId = String(event.active.id);
    const overId = event.over ? String(event.over.id) : null;
    setActiveItemId(null);
    setActiveColumn(null);
    onDragEndItem?.();
    if (!overId) return;

    const fromColumn = findContainerByItemId(value, getItemValue, activeId);
    if (!fromColumn) return;

    const toColumn = value[overId] ? overId : findContainerByItemId(value, getItemValue, overId);
    if (!toColumn) return;

    const fromItems = value[fromColumn] ?? [];
    const fromIndex = fromItems.findIndex((item) => getItemValue(item) === activeId);
    if (fromIndex < 0) return;

    const next: KanbanRecord<T> = { ...value };
    if (fromColumn === toColumn) {
      const items = [...fromItems];
      const overIndex = items.findIndex((item) => getItemValue(item) === overId);
      if (overId === toColumn) {
        const targetIndex = Math.max(0, items.length - 1);
        if (fromIndex === targetIndex) return;
        next[fromColumn] = arrayMove(items, fromIndex, targetIndex);
      } else {
        if (overIndex < 0 || fromIndex === overIndex) return;
        next[fromColumn] = arrayMove(items, fromIndex, overIndex);
      }
      onValueChange(next);
      return;
    }

    const movingItem = fromItems[fromIndex];
    const nextFrom = [...fromItems];
    nextFrom.splice(fromIndex, 1);
    const toItems = [...(value[toColumn] ?? [])];
    const overIndexInTarget = overId === toColumn ? -1 : toItems.findIndex((item) => getItemValue(item) === overId);
    const insertIndex = overIndexInTarget >= 0 ? overIndexInTarget : toItems.length;
    toItems.splice(insertIndex, 0, movingItem);
    next[fromColumn] = nextFrom;
    next[toColumn] = toItems;
    onValueChange(next);
    onItemMove?.({ itemId: activeId, fromColumn, toColumn });
  }, [getItemValue, onDragEndItem, onItemMove, onValueChange, value]);

  return (
    <KanbanContext.Provider
      value={{
        value: value as KanbanRecord<unknown>,
        getItemValue: getItemValue as (item: unknown) => string,
        activeItemId,
        activeColumn,
      }}
    >
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        modifiers={[restrictToWindowEdges]}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
      >
        {children}
      </DndContext>
    </KanbanContext.Provider>
  );
}

export function KanbanBoard({
  children,
  className,
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={["ui-kanban-board", className].filter(Boolean).join(" ")}>{children}</div>;
}

type KanbanColumnProps = React.HTMLAttributes<HTMLDivElement> & {
  value: string;
};

export function KanbanColumn({
  value,
  className,
  children,
  ...props
}: KanbanColumnProps): JSX.Element {
  const { value: columns, getItemValue } = useKanbanContext<unknown>("KanbanColumn");
  const { setNodeRef, isOver } = useDroppable({ id: value });
  const ids = (columns[value] ?? []).map((item) => getItemValue(item));
  return (
    <SortableContext items={ids} strategy={verticalListSortingStrategy}>
      <div
        ref={setNodeRef}
        data-over={isOver ? "true" : "false"}
        className={["ui-kanban-column", className].filter(Boolean).join(" ")}
        {...props}
      >
        {children}
      </div>
    </SortableContext>
  );
}

type KanbanItemProps = {
  value: string;
  asChild?: boolean;
  asHandle?: boolean;
  className?: string;
  children: React.ReactNode;
};

export function KanbanItem({
  value,
  asChild = false,
  asHandle = false,
  className,
  children,
}: KanbanItemProps): JSX.Element {
  const { activeItemId } = useKanbanContext<unknown>("KanbanItem");
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: value });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const Comp = asChild ? Slot : "div";
  return (
    <Comp
      ref={setNodeRef}
      style={style}
      data-state={isDragging ? "dragging" : undefined}
      className={["ui-kanban-item", className, activeItemId === value ? "is-active" : ""].filter(Boolean).join(" ")}
      {...attributes}
      {...listeners}
    >
      {children}
    </Comp>
  );
}

type KanbanOverlayProps = {
  children: React.ReactNode;
};

export function KanbanOverlay({ children }: KanbanOverlayProps): JSX.Element {
  const { activeItemId } = useKanbanContext<unknown>("KanbanOverlay");
  return (
    <DragOverlay>
      {activeItemId ? <div className="ui-kanban-overlay">{children}</div> : null}
    </DragOverlay>
  );
}

type KanbanColumnHandleProps = React.ComponentProps<"button"> & {
  asChild?: boolean;
};

export function KanbanColumnHandle({
  asChild = false,
  className,
  children,
  ...props
}: KanbanColumnHandleProps): JSX.Element {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      type="button"
      className={["ui-kanban-column-handle", className].filter(Boolean).join(" ")}
      {...props}
    >
      {children}
    </Comp>
  );
}
