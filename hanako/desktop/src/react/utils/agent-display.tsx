import { useEffect, useState } from 'react';
import { hanaUrl } from '../hooks/use-hana-fetch';
import type { Agent } from '../types';
import { userFallbackAvatar, yuanFallbackAvatar } from './agent-helpers';
import { displayInitial } from './grapheme';

let agentAvatarVersion = Date.now();

export function refreshAgentAvatarVersion() {
  agentAvatarVersion = Date.now();
}

export interface AgentDisplayInfo {
  id: string;
  displayName: string;
  avatarUrl: string | null;
  fallbackAvatar: string | null;
  yuan?: string;
  isUser: boolean;
}

export function buildAgentDisplayMap(agents: Agent[]): Map<string, Agent> {
  const map = new Map<string, Agent>();
  for (const agent of agents) {
    map.set(agent.id, agent);
    if (agent.name) map.set(agent.name, agent);
  }
  return map;
}

export function resolveAgentDisplayInfo({
  id,
  agents,
  agentMap,
  userName,
  userAvatarUrl,
  fallbackAgentName,
  fallbackAgentYuan,
  fallbackAgentAvatarUrl,
}: {
  id: string | null | undefined;
  agents: Agent[];
  agentMap?: Map<string, Agent>;
  userName?: string | null;
  userAvatarUrl?: string | null;
  fallbackAgentName?: string | null;
  fallbackAgentYuan?: string | null;
  fallbackAgentAvatarUrl?: string | null;
}): AgentDisplayInfo {
  const key = id || '';
  if (key === 'user' || (userName && key === userName)) {
    const displayName = userName || fallbackAgentName || 'user';
    return {
      id: 'user',
      displayName,
      avatarUrl: userAvatarUrl || null,
      fallbackAvatar: userFallbackAvatar(displayName),
      isUser: true,
    };
  }

  const agent = key
    ? (agentMap ? agentMap.get(key) : agents.find((a) => a.id === key || a.name === key))
    : null;

  // Fallback: reverse name match (trimmed). When memberId doesn't match any agent
  // ID (e.g. channel sender "aris" while agent name is "aris "), try matching
  // by display name after trimming whitespace.
  const fallbackAgent = (!agent && key && agents)
    ? agents.find((a) => a.name && a.name.trim() === key.trim()) || null
    : null;

  const resolved = agent || fallbackAgent;
  if (resolved) {
    return {
      id: resolved.id,
      displayName: resolved.name || resolved.id,
      avatarUrl: resolved.hasAvatar ? hanaUrl(`/api/agents/${resolved.id}/avatar?t=${agentAvatarVersion}`) : null,
      fallbackAvatar: yuanFallbackAvatar(resolved.yuan),
      yuan: resolved.yuan,
      isUser: false,
    };
  }

  if (fallbackAgentName || fallbackAgentYuan || fallbackAgentAvatarUrl) {
    return {
      id: key || fallbackAgentName || 'agent',
      displayName: fallbackAgentName || key || 'Agent',
      avatarUrl: fallbackAgentAvatarUrl || null,
      fallbackAvatar: yuanFallbackAvatar(fallbackAgentYuan || undefined),
      yuan: fallbackAgentYuan || undefined,
      isUser: false,
    };
  }

  return {
    id: key,
    displayName: key || 'Agent',
    avatarUrl: null,
    fallbackAvatar: null,
    isUser: false,
  };
}

export function AgentAvatar({
  info,
  className,
  alt,
  title,
  onClick,
}: {
  info: AgentDisplayInfo;
  className?: string;
  alt?: string;
  title?: string;
  onClick?: () => void;
}) {
  const [failedPrimary, setFailedPrimary] = useState(false);
  const [failedFallback, setFailedFallback] = useState(false);

  useEffect(() => {
    setFailedPrimary(false);
    setFailedFallback(false);
  }, [info.avatarUrl, info.fallbackAvatar]);

  const src = !failedPrimary && info.avatarUrl
    ? info.avatarUrl
    : (!failedFallback && info.fallbackAvatar ? info.fallbackAvatar : null);

  if (src) {
    return (
      <img
        className={className}
        src={src}
        alt={alt ?? info.displayName}
        title={title}
        draggable={false}
        onClick={onClick}
        onError={() => {
          if (!failedPrimary && info.avatarUrl) {
            setFailedPrimary(true);
          } else {
            setFailedFallback(true);
          }
        }}
      />
    );
  }

  return (
    <span
      className={className}
      title={title}
      aria-label={alt ?? info.displayName}
      onClick={onClick}
    >
      {displayInitial(info.displayName, '?')}
    </span>
  );
}
