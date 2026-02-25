interface ShimmerTagProps {
  children: string;
}

export function ShimmerTag({ children }: ShimmerTagProps) {
  return <span className="rb-shimmer-tag">{children}</span>;
}
