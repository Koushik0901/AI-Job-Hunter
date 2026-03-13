import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownPreviewProps {
  markdown: string;
  emptyState: string;
}

export default function MarkdownPreview({ markdown, emptyState }: MarkdownPreviewProps): JSX.Element {
  if (!markdown.trim()) {
    return <p className="board-note">{emptyState}</p>;
  }

  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>;
}
