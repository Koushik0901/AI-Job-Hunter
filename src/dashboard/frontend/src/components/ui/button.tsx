import * as React from "react";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

type ButtonVariant = "default" | "primary" | "danger" | "success" | "warn";
type ButtonSize = "default" | "compact";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonProps): JSX.Element {
  const base = variant === "primary" ? "primary-btn" : "ghost-btn";
  return <button className={joinClasses(base, size === "compact" ? "compact" : undefined, variant === "danger" ? "danger" : undefined, variant === "success" ? "success" : undefined, variant === "warn" ? "warn" : undefined, variant === "primary" ? undefined : undefined, className)} {...props} />;
}

