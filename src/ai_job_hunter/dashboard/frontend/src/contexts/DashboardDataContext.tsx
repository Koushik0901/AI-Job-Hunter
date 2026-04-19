import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import {
  getBootstrap,
  getStats,
  getDailyBriefingLatest,
  getConversion,
  getSourceQuality,
  getProfileGaps,
  getProfileInsights,
  getSkillAliases,
  getActionQueue,
  getJobsWithParams,
  subscribeToDashboardEvents,
} from "../api";
import {
  CandidateProfile,
  StatsResponse,
  DailyBriefing,
  ConversionResponse,
  SourceQualityResponse,
  ProfileGapsResponse,
  ProfileInsightsResponse,
  JobAction,
  JobSummary,
} from "../types";


interface DashboardDataContextType {
  profile: CandidateProfile | null;
  stats: StatsResponse | null;
  dailyBriefing: DailyBriefing | null;
  conversion: ConversionResponse | null;
  sourceQuality: SourceQualityResponse | null;
  profileGaps: ProfileGapsResponse | null;
  profileInsights: ProfileInsightsResponse | null;
  recommendedJobs: JobSummary[];
  skillAliases: Record<string, string>;
  actionQueue: JobAction[];
  loading: boolean;
  backgroundLoading: boolean;
  error: string | null;
  refreshData: (options?: { force?: boolean; background?: boolean }) => Promise<void>;
}

const DashboardDataContext = createContext<DashboardDataContextType | undefined>(undefined);

export const DashboardDataProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [dailyBriefing, setDailyBriefing] = useState<DailyBriefing | null>(null);
  const [conversion, setConversion] = useState<ConversionResponse | null>(null);
  const [sourceQuality, setSourceQuality] = useState<SourceQualityResponse | null>(null);
  const [profileGaps, setProfileGaps] = useState<ProfileGapsResponse | null>(null);
  const [profileInsights, setProfileInsights] = useState<ProfileInsightsResponse | null>(null);
  const [recommendedJobs, setRecommendedJobs] = useState<JobSummary[]>([]);
  const [skillAliases, setSkillAliases] = useState<Record<string, string>>({});
  const [actionQueue, setActionQueue] = useState<JobAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [backgroundLoading, setBackgroundLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const initializedRef = useRef(false);
  const liveRefreshTimerRef = useRef<number>(0);

  const refreshData = useCallback(async (options: { force?: boolean; background?: boolean } = {}) => {
    const { force = false, background = false } = options;
    
    const hasData = profile !== null || stats !== null;
    
    if (background || (hasData && !force)) {
      setBackgroundLoading(true);
    } else {
      setLoading(true);
    }
    
    setError(null);
    try {
      const bootstrap = await getBootstrap({ force });
      setProfile(bootstrap.profile);
      setStats(bootstrap.stats);
      setRecommendedJobs(bootstrap.recommended_jobs);
      setActionQueue(bootstrap.action_queue);
      initializedRef.current = true;
      setLoading(false);

      const [db, conv, sq, pg, pi, aliases, aq, rj, freshStats] = await Promise.all([
        getDailyBriefingLatest(),
        getConversion(),
        getSourceQuality(),
        getProfileGaps(),
        getProfileInsights(),
        getSkillAliases(),
        getActionQueue({ force }),
        getJobsWithParams({ sort: "match_desc", limit: 200 }, { force }),
        getStats({ force }),
      ]);

      setDailyBriefing(db);
      setConversion(conv);
      setSourceQuality(sq);
      setProfileGaps(pg);
      setProfileInsights(pi);
      setSkillAliases(aliases);
      setActionQueue(aq.items);
      setRecommendedJobs(rj.items.length > 0 ? rj.items : bootstrap.recommended_jobs);
      setStats(freshStats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard data");
    } finally {
      setLoading(false);
      setBackgroundLoading(false);
    }
  }, [profile]);

  useEffect(() => {
    if (!initializedRef.current) {
      refreshData();
    }
  }, [refreshData]);

  useEffect(() => {
    const unsubscribe = subscribeToDashboardEvents({
      onMessage: () => {
        if (!initializedRef.current) return;
        window.clearTimeout(liveRefreshTimerRef.current);
        liveRefreshTimerRef.current = window.setTimeout(() => {
          void refreshData({ force: true, background: true });
        }, 350);
      },
    });
    return () => {
      window.clearTimeout(liveRefreshTimerRef.current);
      unsubscribe();
    };
  }, [refreshData]);

  return (
    <DashboardDataContext.Provider value={{
      profile,
      stats,
      dailyBriefing,
      conversion,
      sourceQuality,
      profileGaps,
      profileInsights,
      recommendedJobs,
      skillAliases,
      actionQueue,
      loading,
      backgroundLoading,
      error,
      refreshData,
    }}>
      {children}
    </DashboardDataContext.Provider>
  );
};

export const useDashboardData = () => {
  const context = useContext(DashboardDataContext);
  if (context === undefined) {
    throw new Error("useDashboardData must be used within a DashboardDataProvider");
  }
  return context;
};
