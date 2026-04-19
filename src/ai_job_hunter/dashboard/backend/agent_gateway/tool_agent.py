"""
Tool-use agent for freeform chat.

Uses LangChain bind_tools with a manual ReAct loop (no AgentExecutor dependency).
Falls back to legacy_chat if LangChain is unavailable or the model call fails.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_TOOL_MODEL = "openai/gpt-4o"
_MAX_TOOL_ITERATIONS = 5

_SYSTEM_TEMPLATE = """\
You are an AI job search assistant embedded in a personal job search dashboard called "AI Job Hunter".
You help the user manage their job pipeline, optimize application documents, and make strategic decisions.

You have access to tools:
- search_jobs: find roles matching keywords or criteria
- get_job_detail: deep-dive a specific job by its ID
- get_story_match: show which of the user's professional stories best fit a job
- check_ats_pass: analyze whether the current resume will pass ATS screening for a job
- draft_resume: queue generation of a tailored resume for a job

Current pipeline snapshot:
{context}

Guidelines:
- Use tools proactively when the user's question involves specific jobs, ATS screening, or story alignment
- Chain tools when useful: e.g. search_jobs then check_ats_pass on the top result
- Be concise in your final reply — bullet points preferred for lists
- Do not mention job IDs in your reply unless the user specifically asks; use company+title instead
- Tone: professional, direct, encouraging
"""


def handle_tool_agent_chat(messages: list[dict[str, str]], conn: Any) -> dict[str, Any]:
    """
    Run freeform chat with LangChain tool-use.
    Falls back to legacy_chat on import errors or API failures.
    """
    from .legacy_chat import build_agent_context, handle_freeform_chat

    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        return handle_freeform_chat(messages, conn)

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )
        from langchain_core.tools import BaseTool
    except ImportError:
        return handle_freeform_chat(messages, conn)

    from .agent_tools import build_agent_tools

    tools = build_agent_tools(conn)
    if not tools:
        return handle_freeform_chat(messages, conn)

    tool_map: dict[str, BaseTool] = {t.name: t for t in tools}  # type: ignore[attr-defined]
    context = build_agent_context(conn)
    model = (os.getenv("AGENT_STRONG_MODEL") or _DEFAULT_TOOL_MODEL).strip()

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0.3,
        max_tokens=1500,
    ).bind_tools(tools)

    # Build the message list: system + history + latest user message
    system_msg = SystemMessage(content=_SYSTEM_TEMPLATE.format(context=context))
    lc_messages: list[Any] = [system_msg]
    for msg in messages:
        role = str(msg.get("role") or "user")
        content = str(msg.get("content") or "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        else:
            lc_messages.append(AIMessage(content=content))

    try:
        for _iteration in range(_MAX_TOOL_ITERATIONS):
            response = llm.invoke(lc_messages)
            tool_calls = getattr(response, "tool_calls", None) or []

            if not tool_calls:
                # No more tool calls — final answer
                reply = str(getattr(response, "content", "") or "").strip()
                return {
                    "reply": reply,
                    "context_snapshot": context,
                    "response_mode": "tool_agent",
                    "output_kind": "none",
                    "output_payload": None,
                    "operation_id": None,
                }

            # Execute each tool call and append results
            lc_messages.append(response)
            for tc in tool_calls:
                tool_name = str(tc.get("name") or "")
                tool_args = tc.get("args") or {}
                tool_call_id = str(tc.get("id") or "")
                tool_fn = tool_map.get(tool_name)
                if tool_fn is None:
                    tool_output = f"Unknown tool: {tool_name}"
                else:
                    try:
                        tool_output = tool_fn.invoke(tool_args)
                    except Exception as tool_exc:
                        logger.warning("Tool %s raised: %s", tool_name, tool_exc)
                        tool_output = f"Tool error: {tool_exc}"
                logger.debug("Tool %s(%r) -> %s", tool_name, tool_args, str(tool_output)[:120])
                lc_messages.append(
                    ToolMessage(content=str(tool_output), tool_call_id=tool_call_id)
                )

        # Max iterations — return whatever the last content was
        final_content = str(getattr(response, "content", "") or "").strip()
        if not final_content:
            final_content = "I ran the available tools but hit the iteration limit. Try asking a more specific question."
        return {
            "reply": final_content,
            "context_snapshot": context,
            "response_mode": "tool_agent",
            "output_kind": "none",
            "output_payload": None,
            "operation_id": None,
        }

    except Exception as exc:
        logger.exception("Tool agent failed, falling back to legacy chat: %s", exc)
        return handle_freeform_chat(messages, conn)
