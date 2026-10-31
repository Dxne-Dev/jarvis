// Skills, serveurs MCP, agents, mémoire graphe et suggestions.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { EngineClient } from "../client";
import { useEngineStore } from "../store";
import type {
  AgentInfo,
  AgentRun,
  GraphEntity,
  GraphKind,
  GraphRelation,
  McpInstallRequest,
  McpProbe,
  McpRegistryEntry,
  McpServerInfo,
  MemoryGraph,
  Skill,
  SkillDetail,
  SuggestionInfo,
} from "../types";
import { requireClient } from "./shared";

export function useSkills() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => requireClient(client).get<Skill[]>("/v1/skills"),
    enabled: client !== null,
  });
}

export function useSkill(id: string, enabled: boolean) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["skills", id],
    queryFn: () => requireClient(client).get<SkillDetail>(`/v1/skills/${encodeURIComponent(id)}`),
    enabled: client !== null && enabled,
  });
}

function useSkillAction(action: (client: EngineClient, id: string) => Promise<unknown>) {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => action(requireClient(client), id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useTestSkill() {
  return useSkillAction((client, id) =>
    client.post<Skill>(`/v1/skills/${encodeURIComponent(id)}/test`),
  );
}

/** Activer : l'écran a déjà demandé la seconde confirmation (niveau 3). */
export function useActivateSkill() {
  return useSkillAction((client, id) =>
    client.post<Skill>(`/v1/skills/${encodeURIComponent(id)}/activate`, { double_confirm: true }),
  );
}

export function useDisableSkill() {
  return useSkillAction((client, id) =>
    client.post<Skill>(`/v1/skills/${encodeURIComponent(id)}/disable`),
  );
}

export function useDeleteSkill() {
  return useSkillAction((client, id) =>
    client.delete<undefined>(`/v1/skills/${encodeURIComponent(id)}?double_confirm=true`),
  );
}

// ---------------------------------------------------------------- serveurs MCP du registre

export function useMcpServers() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["mcp"],
    queryFn: () => requireClient(client).get<McpServerInfo[]>("/v1/mcp/servers"),
    enabled: client !== null,
  });
}

export function useMcpSearch(query: string) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["mcp", "registre", query],
    queryFn: () =>
      requireClient(client).get<McpRegistryEntry[]>(
        `/v1/mcp/registry?q=${encodeURIComponent(query)}`,
      ),
    enabled: client !== null && query.length >= 2,
    staleTime: 300_000,
  });
}

export function useProbeMcp() {
  const client = useEngineStore((s) => s.client);
  return useMutation({
    mutationFn: (request: McpInstallRequest) =>
      requireClient(client).post<McpProbe>("/v1/mcp/probe", request),
  });
}

/** Installer : l'écran a déjà demandé la seconde confirmation (niveau 3). */
export function useInstallMcp() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: McpInstallRequest) =>
      requireClient(client).post<McpServerInfo>("/v1/mcp/servers", {
        ...request,
        double_confirm: true,
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["mcp"] }),
  });
}

export function useToggleMcp() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      requireClient(client).patch<McpServerInfo>(`/v1/mcp/servers/${encodeURIComponent(id)}`, {
        enabled,
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["mcp"] }),
  });
}

export function useUninstallMcp() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      requireClient(client).delete<undefined>(
        `/v1/mcp/servers/${encodeURIComponent(id)}?double_confirm=true`,
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["mcp"] }),
  });
}

// ---------------------------------------------------------------- agents

export function useAgents() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => requireClient(client).get<AgentInfo[]>("/v1/agents"),
    enabled: client !== null,
  });
}

export function useAgentRuns() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["agents", "runs"],
    queryFn: () => requireClient(client).get<AgentRun[]>("/v1/agents/runs?limit=20"),
    enabled: client !== null,
  });
}

export function useStartMission() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agent, task }: { agent: string; task: string }) =>
      requireClient(client).post<AgentRun>(`/v1/agents/${encodeURIComponent(agent)}/runs`, {
        task,
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
  });
}

// ---------------------------------------------------------------- mémoire graphe

export function useMemoryGraph() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["memory", "graph"],
    queryFn: () => requireClient(client).get<MemoryGraph>("/v1/memory/graph"),
    enabled: client !== null,
  });
}

function useGraphMutation<T>(action: (client: EngineClient, input: T) => Promise<unknown>) {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: T) => action(requireClient(client), input),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["memory", "graph"] }),
  });
}

export function useAddEntity() {
  return useGraphMutation((client, input: { name: string; kind: GraphKind; description: string }) =>
    client.post<GraphEntity>("/v1/memory/graph/entities", input),
  );
}

export function useUpdateEntity() {
  return useGraphMutation(
    (client, { id, ...changes }: { id: number; name?: string; description?: string }) =>
      client.patch<GraphEntity>(`/v1/memory/graph/entities/${id}`, changes),
  );
}

export function useDeleteEntity() {
  return useGraphMutation((client, id: number) =>
    client.delete<undefined>(`/v1/memory/graph/entities/${id}`),
  );
}

export function useAddRelation() {
  return useGraphMutation(
    (client, input: { source_id: number; label: string; target_id: number }) =>
      client.post<GraphRelation>("/v1/memory/graph/relations", input),
  );
}

export function useDeleteRelation() {
  return useGraphMutation((client, id: number) =>
    client.delete<undefined>(`/v1/memory/graph/relations/${id}`),
  );
}

// ---------------------------------------------------------------- suggestions

export function useSuggestions() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["suggestions"],
    queryFn: () => requireClient(client).get<SuggestionInfo[]>("/v1/suggestions"),
    enabled: client !== null,
  });
}

export function useAcceptSuggestion() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, option }: { id: string; option: string }) =>
      requireClient(client).post<SuggestionInfo>(
        `/v1/suggestions/${encodeURIComponent(id)}/accept`,
        { option },
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["suggestions"] }),
  });
}

export function useDismissSuggestion() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      requireClient(client).post<SuggestionInfo>(
        `/v1/suggestions/${encodeURIComponent(id)}/dismiss`,
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["suggestions"] }),
  });
}
