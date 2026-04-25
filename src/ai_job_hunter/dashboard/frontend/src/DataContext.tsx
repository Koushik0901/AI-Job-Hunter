// Shared bootstrap / stories / profile fetch + Kenji agent chat state.
// Chat state lives here (not in Command.tsx) so the conversation persists across
// nav, and so a new agent reply can flip an "unread" flag for the Command nav
// item when the user is on a different screen.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import {
  api,
  type AgentChatRequest,
  type AgentChatResponse,
  type BootstrapResponse,
  type CandidateProfile,
  type JobSummary,
  type StatsResponse,
  type UserStory,
} from "./api";

export interface AgentChatMsg {
  role: "user" | "assistant";
  content: string;
  time: string;
  meta?: {
    mode?: string;
    kind?: AgentChatResponse["output_kind"];
    payload?: Record<string, unknown> | null;
  };
}

interface DataState {
  loading: boolean;
  error: string | null;
  profile: CandidateProfile | null;
  stats: StatsResponse | null;
  recommendedJobs: JobSummary[];
  stories: UserStory[];
  refreshAll: () => Promise<void>;
  refreshStories: () => Promise<void>;

  // Agent chat — lifted from Command so it survives nav and can mark unread.
  agentMessages: AgentChatMsg[];
  setAgentMessages: React.Dispatch<React.SetStateAction<AgentChatMsg[]>>;
  agentSending: boolean;
  agentError: string | null;
  agentUnread: boolean;
  markAgentRead: () => void;
  setOnAgentScreen: (on: boolean) => void;
  sendAgentMessage: (text: string, opts?: { skillInvocation?: AgentChatRequest["skill_invocation"] }) => Promise<void>;
}

const Ctx = createContext<DataState | null>(null);

function nowStamp() {
  return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function DataProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [boot, setBoot] = useState<BootstrapResponse | null>(null);
  const [stories, setStories] = useState<UserStory[]>([]);

  const [agentMessages, setAgentMessages] = useState<AgentChatMsg[]>([]);
  const [agentSending, setAgentSending] = useState(false);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [agentUnread, setAgentUnread] = useState(false);
  const onAgentScreenRef = useRef(false);

  const refreshStories = useCallback(async () => {
    try { setStories(await api.listStories()); } catch (e) { console.warn("stories fetch failed", e); }
  }, []);

  const refreshAll = useCallback(async () => {
    setError(null);
    try {
      const [b, s] = await Promise.all([api.bootstrap(), api.listStories().catch(() => [])]);
      setBoot(b);
      setStories(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  const markAgentRead = useCallback(() => setAgentUnread(false), []);

  const setOnAgentScreen = useCallback((on: boolean) => {
    onAgentScreenRef.current = on;
    if (on) setAgentUnread(false);
  }, []);

  const sendAgentMessage = useCallback(async (
    text: string,
    opts: { skillInvocation?: AgentChatRequest["skill_invocation"] } = {},
  ) => {
    if (!text.trim()) return;
    setAgentError(null);
    const userMsg: AgentChatMsg = { role: "user", content: text, time: nowStamp() };
    let nextWire: AgentChatRequest["messages"] = [];
    setAgentMessages(prev => {
      const next = [...prev, userMsg];
      nextWire = next.filter(m => m.content.length > 0).map(m => ({ role: m.role, content: m.content }));
      return next;
    });
    setAgentSending(true);

    try {
      const res = await api.agentChat({
        messages: nextWire,
        skill_invocation: opts.skillInvocation,
      });
      setAgentMessages(prev => [...prev, {
        role: "assistant",
        content: res.reply,
        time: nowStamp(),
        meta: { mode: res.response_mode, kind: res.output_kind, payload: res.output_payload },
      }]);
      // Reply landed while user is elsewhere — surface a subtle nav indicator.
      if (!onAgentScreenRef.current) setAgentUnread(true);
    } catch (e) {
      setAgentError(e instanceof Error ? e.message : String(e));
    } finally {
      setAgentSending(false);
    }
  }, []);

  const value: DataState = {
    loading,
    error,
    profile: boot?.profile ?? null,
    stats: boot?.stats ?? null,
    recommendedJobs: boot?.recommended_jobs ?? [],
    stories,
    refreshAll,
    refreshStories,
    agentMessages,
    setAgentMessages,
    agentSending,
    agentError,
    agentUnread,
    markAgentRead,
    setOnAgentScreen,
    sendAgentMessage,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useData() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useData outside DataProvider");
  return v;
}
