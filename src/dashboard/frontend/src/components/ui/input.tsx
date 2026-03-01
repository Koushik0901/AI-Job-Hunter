import * as React from "react";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Input({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>): JSX.Element {
  return <input className={joinClasses("ui-input", className)} {...props} />;
}

