import { useRef, useState } from "react";

type FileUploadProps = {
  accept?: string;
  disabled?: boolean;
  onFileSelect: (file: File) => void | Promise<void>;
  title?: string;
  hint?: string;
};

export function FileUpload({
  accept = "application/pdf,.pdf",
  disabled = false,
  onFileSelect,
  title = "Import From Resume",
  hint = "Drop a PDF here or click to browse",
}: FileUploadProps): JSX.Element {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  function pickFile(file: File | null): void {
    if (!file || disabled) return;
    void onFileSelect(file);
  }

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      className={`ui-file-upload ${isDragging ? "dragging" : ""} ${disabled ? "disabled" : ""}`}
      onClick={() => {
        if (!disabled) inputRef.current?.click();
      }}
      onKeyDown={(event) => {
        if (disabled) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(event) => {
        if (disabled) return;
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        if (disabled) return;
        event.preventDefault();
        setIsDragging(false);
        const file = event.dataTransfer.files?.[0] ?? null;
        pickFile(file);
      }}
      aria-disabled={disabled}
      aria-label={title}
    >
      <div className="ui-file-upload-title">{title}</div>
      <p className="ui-file-upload-hint">{hint}</p>
      <button
        type="button"
        className="ghost-btn compact info"
        data-icon="↑"
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          if (!disabled) inputRef.current?.click();
        }}
      >
        Choose PDF
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="visually-hidden-input"
        onChange={(event) => {
          const nextFile = event.target.files?.[0] ?? null;
          pickFile(nextFile);
          event.target.value = "";
        }}
      />
    </div>
  );
}
