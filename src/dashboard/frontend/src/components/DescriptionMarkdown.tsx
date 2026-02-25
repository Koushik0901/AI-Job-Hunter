import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface DescriptionMarkdownProps {
  markdown: string;
}

export function DescriptionMarkdown({ markdown }: DescriptionMarkdownProps) {
  return (
    <div className="description-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h4 className="description-subhead">{children}</h4>,
          h2: ({ children }) => <h4 className="description-subhead">{children}</h4>,
          h3: ({ children }) => <h4 className="description-subhead">{children}</h4>,
          h4: ({ children }) => <h4 className="description-subhead">{children}</h4>,
          p: ({ children }) => <p className="description-text">{children}</p>,
          ul: ({ children }) => <ul className="description-list">{children}</ul>,
          ol: ({ children }) => <ol className="description-list ordered">{children}</ol>,
          hr: () => <hr className="description-divider" />,
          table: ({ children }) => <table className="description-table">{children}</table>,
          thead: ({ children }) => <thead className="description-table-head">{children}</thead>,
          tbody: ({ children }) => <tbody className="description-table-body">{children}</tbody>,
          tr: ({ children }) => <tr className="description-table-row">{children}</tr>,
          th: ({ children }) => <th className="description-table-cell header">{children}</th>,
          td: ({ children }) => <td className="description-table-cell">{children}</td>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
