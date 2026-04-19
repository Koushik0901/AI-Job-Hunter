import { memo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface DescriptionMarkdownProps {
  markdown: string;
}

const markdownComponents = {
  h1: ({ children }: { children?: ReactNode }) => <h4 className="description-subhead">{children}</h4>,
  h2: ({ children }: { children?: ReactNode }) => <h4 className="description-subhead">{children}</h4>,
  h3: ({ children }: { children?: ReactNode }) => <h4 className="description-subhead">{children}</h4>,
  h4: ({ children }: { children?: ReactNode }) => <h4 className="description-subhead">{children}</h4>,
  p: ({ children }: { children?: ReactNode }) => <p className="description-text">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => <ul className="description-list">{children}</ul>,
  ol: ({ children }: { children?: ReactNode }) => <ol className="description-list ordered">{children}</ol>,
  hr: () => <hr className="description-divider" />,
  table: ({ children }: { children?: ReactNode }) => <table className="description-table">{children}</table>,
  thead: ({ children }: { children?: ReactNode }) => <thead className="description-table-head">{children}</thead>,
  tbody: ({ children }: { children?: ReactNode }) => <tbody className="description-table-body">{children}</tbody>,
  tr: ({ children }: { children?: ReactNode }) => <tr className="description-table-row">{children}</tr>,
  th: ({ children }: { children?: ReactNode }) => <th className="description-table-cell header">{children}</th>,
  td: ({ children }: { children?: ReactNode }) => <td className="description-table-cell">{children}</td>,
};

export const DescriptionMarkdown = memo(function DescriptionMarkdown({ markdown }: DescriptionMarkdownProps) {
  return (
    <div className="description-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
});
