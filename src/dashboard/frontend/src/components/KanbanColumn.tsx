import { type ReactNode } from "react";

interface KanbanColumnProps {
  id: string;
  label: string;
  count: number;
  isActiveDrop: boolean;
  onDropJob: (status: string, url: string) => void;
  hasMore: boolean;
  onLoadMore: () => void;
  children: ReactNode;
}

export function KanbanColumn({
  id,
  label,
  count,
  isActiveDrop,
  onDropJob,
  hasMore,
  onLoadMore,
  children,
}: KanbanColumnProps) {
  return (
    <section
      className={`kanban-column ${isActiveDrop ? "drop-active" : ""}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const url = event.dataTransfer.getData("text/job-url");
        if (url) {
          onDropJob(id, url);
        }
      }}
    >
      <header className="column-header">
        <div className="column-header-title">
          <h3>{label}</h3>
          <span className="column-count">{count}</span>
        </div>
      </header>
      <div className="column-items">{children}</div>
      {hasMore && (
        <button type="button" className="column-load-more" onClick={onLoadMore}>
          Load more
        </button>
      )}
    </section>
  );
}
