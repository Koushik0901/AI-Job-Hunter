import * as React from "react";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Separator({
  className,
  orientation = "horizontal",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { orientation?: "horizontal" | "vertical" }): JSX.Element {
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={joinClasses("ui-separator", orientation === "vertical" ? "vertical" : undefined, className)}
      {...props}
    />
  );
}

