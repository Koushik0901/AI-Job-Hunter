/* discover.jsx — job feed */

const JobCard = ({ job, onOpen, pinned, onPin, rank }) => {
  const [expanded, setExpanded] = useState(false);
  const top = job.match >= 90;
  return (
    <div className="card" style={{ padding: 0, position: "relative", overflow: "hidden" }}>
      {top && <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(to right, transparent, var(--accent), transparent)", opacity: 0.6 }}/>}
      <div style={{ display: "grid", gridTemplateColumns: "48px 1fr auto", gap: 18, padding: "20px 22px", alignItems: "flex-start" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, paddingTop: 2 }}>
          <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: "0.08em" }}>{String(rank).padStart(2, "0")}</div>
          <ScoreRing value={job.match} size={44}/>
        </div>

        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <CoLogo letter={job.logo} color={job.logoColor} size={22}/>
            <span style={{ fontSize: 12.5, color: "var(--ink-2)", fontWeight: 500 }}>{job.company}</span>
            <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)" }}>·</span>
            <span className="chip ghost mono">{job.size}</span>
            <span className="chip ghost mono">{job.source}</span>
          </div>
          <div style={{ fontSize: 18, fontWeight: 400, letterSpacing: "-0.01em", marginBottom: 6, color: "var(--ink)", fontFamily: "var(--font-serif)" }}>{job.role}</div>
          <div style={{ display: "flex", gap: 14, fontSize: 12, color: "var(--ink-3)", marginBottom: 14 }}>
            <span className="hstack" style={{ gap: 6 }}><Icon name="globe" size={11}/>{job.location}</span>
            <span className="mono" style={{ color: "var(--ink-2)" }}>{job.comp}</span>
            <span className="mono">{job.posted} ago</span>
          </div>

          <div style={{ position: "relative", paddingLeft: 14 }}>
            <div style={{ position: "absolute", left: 0, top: 2, bottom: 2, width: 2, background: "var(--accent)", borderRadius: 2, opacity: 0.7 }}/>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--accent)", letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 6 }}>
              Kenji's read
            </div>
            <div style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-2)" }}>
              {job.reasoning}
            </div>
          </div>

          {expanded && (
            <div className="fade-in" style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 22, marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
              <Radar axes={job.axes} size={150}/>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                {Object.entries(job.axes).map(([k,v]) => (
                  <div key={k} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)", width: 78, letterSpacing: "0.04em" }}>{k}</div>
                    <BarMeter value={v} color={v >= 85 ? "var(--accent)" : v >= 65 ? "var(--ink-3)" : "var(--warn)"}/>
                    <div className="mono" style={{ fontSize: 11, color: "var(--ink-2)", width: 26, textAlign: "right" }}>{v}</div>
                  </div>
                ))}
                <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                  <span className="chip accent mono">grounded: s1</span>
                  <span className="chip accent mono">grounded: s4</span>
                  <span className="chip mono">grounded: s5</span>
                </div>
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
            <button className="btn primary sm" onClick={onOpen}>
              <Icon name="wand" size={12}/>Tailor & apply
            </button>
            <button className="btn sm" onClick={() => setExpanded(!expanded)}>
              {expanded ? "Hide breakdown" : "Breakdown"}
              <Icon name={expanded ? "chevronDown" : "chevron"} size={11}/>
            </button>
            <button className="btn ghost sm" onClick={onPin} style={{ color: pinned ? "var(--accent)" : undefined }}>
              <Icon name="pin" size={12}/>{pinned ? "Pinned" : "Pin"}
            </button>
            <div style={{ flex: 1 }}/>
            <button className="btn ghost sm"><Icon name="external" size={12}/>Source</button>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          {top && <span className="chip accent mono">top match</span>}
        </div>
      </div>
    </div>
  );
};

const Discover = ({ onOpenJob }) => {
  const [pinned, setPinned] = useState(new Set(["j1"]));
  const [filter, setFilter] = useState("all");
  const jobs = window.KENJI_DATA.jobs;
  const filtered = useMemo(() => {
    if (filter === "top") return jobs.filter(j => j.match >= 85);
    if (filter === "remote") return jobs.filter(j => j.location.toLowerCase().includes("remote"));
    if (filter === "pinned") return jobs.filter(j => pinned.has(j.id));
    return jobs;
  }, [filter, pinned, jobs]);

  return (
    <div className="content">
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 40, alignItems: "end", marginBottom: 36, paddingBottom: 24, borderBottom: "1px solid var(--line)" }}>
        <div>
          <div className="overline" style={{ marginBottom: 14 }}>Discover · scan 2,184</div>
          <div className="headline">
            Roles you might<br/><em>actually want.</em>
          </div>
          <div style={{ fontSize: 13.5, color: "var(--ink-3)", marginTop: 14, maxWidth: 540, lineHeight: 1.55 }}>
            Ranked against your 5 stories — not keywords. Kenji scanned{" "}
            <span className="mono" style={{ color: "var(--ink-2)" }}>2,184</span> postings from{" "}
            <span className="mono" style={{ color: "var(--ink-2)" }}>3 sources</span> in the last 6 hours.
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
          {[
            ["scanned", "2,184", "postings"],
            ["ranked", "124", "matched ≥ 50"],
            ["applied", "8", "this week"],
          ].map(([k, v, sub]) => (
            <div key={k} style={{ padding: "14px 14px 16px", borderTop: "1px solid var(--line)" }}>
              <div className="mono" style={{ fontSize: 9.5, color: "var(--ink-4)", letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 8 }}>{k}</div>
              <div className="serif" style={{ fontSize: 30, letterSpacing: "-0.02em", lineHeight: 1, color: "var(--ink)" }}>{v}</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)", marginTop: 4 }}>{sub}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 20, alignItems: "center" }}>
        {[
          ["all", `All · ${jobs.length}`],
          ["top", `Top · ${jobs.filter(j => j.match >= 85).length}`],
          ["remote", `Remote · ${jobs.filter(j => j.location.toLowerCase().includes("remote")).length}`],
          ["pinned", `Pinned · ${pinned.size}`],
        ].map(([id, label]) => (
          <button key={id} className={"btn sm " + (filter === id ? "accent-ghost" : "ghost")} onClick={() => setFilter(id)}>{label}</button>
        ))}
        <div style={{ flex: 1 }}/>
        <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: "0.08em" }}>sort by match · desc</span>
        <button className="btn ghost sm"><Icon name="sliders" size={12}/>Filter</button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }} className="stagger">
        {filtered.map((j, i) => (
          <JobCard key={j.id} job={j} rank={i + 1}
            onOpen={() => onOpenJob(j)}
            pinned={pinned.has(j.id)}
            onPin={() => {
              const n = new Set(pinned);
              if (n.has(j.id)) n.delete(j.id); else n.add(j.id);
              setPinned(n);
            }}/>
        ))}
      </div>
    </div>
  );
};

Object.assign(window, { Discover });
