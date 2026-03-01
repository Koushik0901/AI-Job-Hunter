import * as React from "react";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>): JSX.Element {
  return <label className={joinClasses("ui-label", className)} {...props} />;
}

