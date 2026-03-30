import * as React from "react";

function joinClasses(...classes: Array<string | undefined | false>): string {
  return classes.filter(Boolean).join(" ");
}

interface VisuallyHiddenProps extends React.HTMLAttributes<HTMLSpanElement> {}

export const VisuallyHidden = React.forwardRef<HTMLSpanElement, VisuallyHiddenProps>(function VisuallyHidden(
  { className, ...props },
  ref,
) {
  return <span ref={ref} className={joinClasses("sr-only", className)} {...props} />;
});
