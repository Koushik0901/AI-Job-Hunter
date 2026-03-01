import { EditorContent, useEditor } from "@tiptap/react";
import Link from "@tiptap/extension-link";
import Underline from "@tiptap/extension-underline";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";

interface RichTextEditorProps {
  value: string;
  onChange: (html: string) => void;
  minHeight?: number;
}

function iconButtonClass(active: boolean): string {
  return `richtext-toolbar-btn ${active ? "active" : ""}`;
}

export function RichTextEditor({ value, onChange, minHeight = 160 }: RichTextEditorProps): JSX.Element {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
      }),
      Underline,
      Link.configure({
        openOnClick: false,
        autolink: true,
      }),
    ],
    content: value || "<ul><li></li></ul>",
    editorProps: {
      attributes: {
        class: "richtext-editor-content",
      },
    },
    onUpdate: ({ editor: instance }) => {
      onChange(instance.getHTML());
    },
  });

  useEffect(() => {
    if (!editor) return;
    if (value !== editor.getHTML()) {
      editor.commands.setContent(value || "<ul><li></li></ul>", false);
    }
  }, [editor, value]);

  if (!editor) {
    return <div className="richtext-shell">Loading editor...</div>;
  }

  return (
    <div className="richtext-shell">
      <div className="richtext-toolbar">
        <button type="button" className={iconButtonClass(editor.isActive("bold"))} onClick={() => editor.chain().focus().toggleBold().run()} aria-label="Bold">B</button>
        <button type="button" className={iconButtonClass(editor.isActive("italic"))} onClick={() => editor.chain().focus().toggleItalic().run()} aria-label="Italic">I</button>
        <button type="button" className={iconButtonClass(editor.isActive("underline"))} onClick={() => editor.chain().focus().toggleUnderline().run()} aria-label="Underline">U</button>
        <button type="button" className={iconButtonClass(editor.isActive("strike"))} onClick={() => editor.chain().focus().toggleStrike().run()} aria-label="Strike">S</button>
        <span className="richtext-toolbar-sep" />
        <button type="button" className={iconButtonClass(editor.isActive("bulletList"))} onClick={() => editor.chain().focus().toggleBulletList().run()} aria-label="Bulleted List">•</button>
        <button type="button" className={iconButtonClass(editor.isActive("orderedList"))} onClick={() => editor.chain().focus().toggleOrderedList().run()} aria-label="Numbered List">1.</button>
        <button type="button" className={iconButtonClass(false)} onClick={() => editor.chain().focus().setHardBreak().run()} aria-label="Line Break">≡</button>
        <span className="richtext-toolbar-sep" />
        <button
          type="button"
          className={iconButtonClass(editor.isActive("link"))}
          onClick={() => {
            const current = editor.getAttributes("link").href as string | undefined;
            const href = window.prompt("Enter URL", current ?? "https://");
            if (href === null) return;
            const cleaned = href.trim();
            if (!cleaned) {
              editor.chain().focus().unsetLink().run();
              return;
            }
            editor.chain().focus().extendMarkRange("link").setLink({ href: cleaned }).run();
          }}
        >
          ↗
        </button>
        <button type="button" className={iconButtonClass(false)} onClick={() => editor.chain().focus().unsetAllMarks().run()} aria-label="Clear Formatting">⨯</button>
      </div>
      <EditorContent editor={editor} className="richtext-editor" style={{ minHeight }} />
    </div>
  );
}
