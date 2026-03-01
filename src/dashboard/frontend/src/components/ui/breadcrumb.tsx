import * as React from "react";

function joinClasses(...classes: Array<string | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Breadcrumb({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"nav">): JSX.Element {
  return <nav aria-label="breadcrumb" className={joinClasses("ui-breadcrumb", className)} {...props} />;
}

export function BreadcrumbList({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"ol">): JSX.Element {
  return <ol className={joinClasses("ui-breadcrumb-list", className)} {...props} />;
}

export function BreadcrumbItem({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"li">): JSX.Element {
  return <li className={joinClasses("ui-breadcrumb-item", className)} {...props} />;
}

export function BreadcrumbLink({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"a">): JSX.Element {
  return <a className={joinClasses("ui-breadcrumb-link", className)} {...props} />;
}

export function BreadcrumbPage({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"span">): JSX.Element {
  return <span aria-current="page" className={joinClasses("ui-breadcrumb-page", className)} {...props} />;
}

export function BreadcrumbSeparator({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"li">): JSX.Element {
  return (
    <li aria-hidden="true" className={joinClasses("ui-breadcrumb-separator", className)} {...props}>
      /
    </li>
  );
}

