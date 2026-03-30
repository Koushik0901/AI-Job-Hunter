import * as React from "react";
import { Slot } from "@radix-ui/react-slot";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

type ButtonVariant = "default" | "primary" | "danger" | "success" | "warn";
type ButtonSize = "default" | "compact";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    className,
    variant = "default",
    size = "default",
    asChild = false,
    type,
    ...props
  },
  ref,
): JSX.Element {
  const Comp = asChild ? Slot : "button";
  const base = variant === "primary" ? "primary-btn" : "ghost-btn";
  const resolvedType = asChild ? undefined : (type ?? "button");
  return (
    <Comp
      ref={ref}
      className={joinClasses(
        base,
        size === "compact" ? "compact" : undefined,
        variant === "danger" ? "danger" : undefined,
        variant === "success" ? "success" : undefined,
        variant === "warn" ? "warn" : undefined,
        className,
      )}
      type={resolvedType}
      {...props}
    />
  );
});
