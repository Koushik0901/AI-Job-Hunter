import Editor from "@monaco-editor/react";
import type { editor as MonacoEditor } from "monaco-editor";
import type * as Monaco from "monaco-editor";
import "monaco-editor/esm/vs/language/json/monaco.contribution";

interface LazyMonacoEditorProps {
  beforeMount?: (monaco: typeof Monaco) => void;
  height: string | number;
  language: string;
  path: string;
  theme: "vs" | "vs-dark";
  value: string;
  onChange: (value: string | undefined) => void;
  options: MonacoEditor.IStandaloneEditorConstructionOptions;
}

export default function LazyMonacoEditor(props: LazyMonacoEditorProps): JSX.Element {
  return <Editor {...props} />;
}
