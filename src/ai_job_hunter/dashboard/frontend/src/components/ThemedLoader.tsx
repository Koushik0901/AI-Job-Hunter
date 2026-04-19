interface ThemedLoaderProps {
  label?: string;
}

export function ThemedLoader({ label = "Loading" }: ThemedLoaderProps) {
  return (
    <div className="loading-state" role="status" aria-live="polite" aria-label={label}>
      <div className="loader-stack">
        <div aria-label="Hamster running in a wheel" role="img" className="wheel-and-hamster">
          <div className="wheel" />
          <div className="hamster">
            <div className="hamster__body">
              <div className="hamster__head">
                <div className="hamster__ear" />
                <div className="hamster__eye" />
                <div className="hamster__nose" />
              </div>
              <div className="hamster__limb hamster__limb--fr" />
              <div className="hamster__limb hamster__limb--fl" />
              <div className="hamster__limb hamster__limb--br" />
              <div className="hamster__limb hamster__limb--bl" />
              <div className="hamster__tail" />
            </div>
          </div>
          <div className="spoke" />
        </div>
        <p className="loader-caption">{label}</p>
      </div>
    </div>
  );
}
