import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  getConversion,
  getProfileGaps,
  getProfileInsights,
  getSourceQuality,
} from "../api";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import type {
  ConversionResponse,
  ProfileGapsResponse,
  ProfileInsightsResponse,
  SourceQualityResponse,
} from "../types";

const pageEase = [0.22, 0.84, 0.24, 1] as [number, number, number, number];

const pageRevealVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.05,
    },
  },
};

const sectionRevealVariants = {
  hidden: { opacity: 0, y: 22 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.42, ease: pageEase },
  },
};

export function InsightsPage() {
  const navigate = useNavigate();
  const [conversion, setConversion] = useState<ConversionResponse | null>(null);
  const [sourceQuality, setSourceQuality] = useState<SourceQualityResponse | null>(null);
  const [profileGaps, setProfileGaps] = useState<ProfileGapsResponse | null>(null);
  const [insights, setInsights] = useState<ProfileInsightsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadInsights(): Promise<void> {
      setError(null);
      try {
        const [conversionData, sourceData, gapsData, insightsData] = await Promise.all([
          getConversion(),
          getSourceQuality(),
          getProfileGaps(),
          getProfileInsights(),
        ]);
        setConversion(conversionData);
        setSourceQuality(sourceData);
        setProfileGaps(gapsData);
        setInsights(insightsData);
      } catch (fetchError) {
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load insights");
      }
    }
    void loadInsights();
  }, []);

  return (
    <motion.div
      className="dashboard-page insights-page"
      variants={pageRevealVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.section className="page-hero" variants={sectionRevealVariants}>
        <div>
          <p className="page-kicker">Insights</p>
          <h2>Longer-horizon search strategy</h2>
          <p className="page-lede">
            Use this page to understand what is converting, which sources are worth more effort, and which profile gaps are blocking your strongest opportunities.
          </p>
        </div>
        <div className="page-hero-actions">
          <Button type="button" variant="default" onClick={() => navigate("/today")}>Open Today</Button>
          <Button type="button" variant="default" onClick={() => navigate("/board")}>Open Board</Button>
        </div>
      </motion.section>

      {error ? <div className="error-banner">{error}</div> : null}

      <motion.section className="assistant-grid" aria-label="Insights panels" variants={sectionRevealVariants}>
        <article className="assistant-panel">
          <div className="assistant-panel-head">
            <div>
              <p className="page-kicker">Conversion</p>
              <h3>Interview Conversion</h3>
            </div>
            <Badge>{conversion?.overall.responses ?? 0} responses</Badge>
          </div>
          <div className="assistant-metric-grid">
            <div className="assistant-metric-card">
              <span>Applied</span>
              <strong>{conversion?.overall.applied ?? 0}</strong>
            </div>
            <div className="assistant-metric-card">
              <span>Interviews</span>
              <strong>{conversion?.overall.interviews ?? 0}</strong>
            </div>
            <div className="assistant-metric-card">
              <span>Offers</span>
              <strong>{conversion?.overall.offers ?? 0}</strong>
            </div>
          </div>
          <div className="assistant-insight-block">
            <strong>Role-family trends</strong>
            <ul className="assistant-bullet-list">
              {(conversion?.by_role_family ?? []).slice(0, 4).map((item) => (
                <li key={item.key}>
                  {item.key}: {item.responses} responses from {item.applied} applications
                </li>
              ))}
            </ul>
          </div>
        </article>

        <article className="assistant-panel">
          <div className="assistant-panel-head">
            <div>
              <p className="page-kicker">Sources</p>
              <h3>Source Quality</h3>
            </div>
            <Badge>{sourceQuality?.items.length ?? 0} sources</Badge>
          </div>
          <div className="assistant-action-list">
            {(sourceQuality?.items ?? []).slice(0, 6).map((item) => (
              <article key={item.ats} className="assistant-action-card">
                <div className="assistant-action-copy">
                  <strong>{item.ats}</strong>
                  <p>
                    Quality {item.quality_score}/100 · {item.positive_outcomes} positive outcomes · {item.negative_outcomes} negative outcomes
                  </p>
                </div>
              </article>
            ))}
            {(sourceQuality?.items.length ?? 0) === 0 ? (
              <p className="empty-text tiny">Source quality will become useful once more outcomes accumulate.</p>
            ) : null}
          </div>
        </article>

        <article className="assistant-panel">
          <div className="assistant-panel-head">
            <div>
              <p className="page-kicker">Profile</p>
              <h3>Gap Analysis</h3>
            </div>
            <Badge>{profileGaps?.items.length ?? 0} blockers</Badge>
          </div>
          <div className="assistant-insight-block">
            <strong>Top missing signals</strong>
            <div className="assistant-chip-list">
              {(profileGaps?.items ?? []).slice(0, 6).map((gap) => (
                <span key={`${gap.kind}-${gap.label}`} className="assistant-gap-chip">
                  {gap.label} · {gap.count}
                </span>
              ))}
            </div>
          </div>
          {insights?.suggested_profile_updates?.length ? (
            <div className="assistant-insight-block">
              <strong>Suggested updates</strong>
              <ul className="assistant-bullet-list">
                {insights.suggested_profile_updates.slice(0, 4).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {(insights?.roles_you_should_target_more?.length ?? 0) > 0 ? (
            <div className="assistant-insight-block">
              <strong>Target more</strong>
              <div className="assistant-chip-list">
                {insights?.roles_you_should_target_more.slice(0, 4).map((item) => (
                  <span key={item} className="assistant-gap-chip positive">{item}</span>
                ))}
              </div>
            </div>
          ) : null}
        </article>
      </motion.section>
    </motion.div>
  );
}
