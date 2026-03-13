import * as React from "react";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>): JSX.Element {
  return <textarea className={joinClasses("ui-textarea", className)} {...props} />;
}

export const TextareaWithRef = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea ref={ref} className={joinClasses("ui-textarea", className)} {...props} />
  ),
);
TextareaWithRef.displayName = "TextareaWithRef";
