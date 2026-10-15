import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { EngineClient } from "./client";
import { useEngineStore } from "./store";
import type {
  CheckResult,
  Conversation,
  ConversationDetail,
  EngineStatus,
  MemoryItem,
  MemoryKind,
  ModelInfo,
  ProviderStatus,
  PerfReport,
  Preferences,
  SecretStatus,
  TraceDetail,
  TraceSummary,
} from "./types";

function requireClient(client: EngineClient | null): EngineClient {
  if (!client) throw new Error("Moteur indisponible.");
  return client;
}

export function useStatus() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["status"],
    queryFn: () => requireClient(client).get<EngineStatus>("/v1/status"),
    enabled: client !== null,
  });
}

export function useSecrets() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["secrets"],
    queryFn: () => requireClient(client).get<SecretStatus[]>("/v1/secrets"),
    enabled: client !== null,
  });
}

export function useSaveSecret() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) =>
      requireClient(client).put<undefined>(`/v1/secrets/${encodeURIComponent(name)}`, { value }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["secrets"] }),
  });
}

export function useDeleteSecret() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      requireClient(client).delete<undefined>(`/v1/secrets/${encodeURIComponent(name)}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["secrets"] }),
  });
}

export function useCheckSecret() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      requireClient(client).post<CheckResult>(`/v1/secrets/${encodeURIComponent(name)}/check`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["secrets"] });
      void queryClient.invalidateQueries({ queryKey: ["traces"] });
    },
  });
}

export function usePreferences() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => requireClient(client).get<Preferences>("/v1/settings"),
    enabled: client !== null,
  });
}

export function useUpdatePreferences() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: Partial<Preferences>) =>
      requireClient(client).patch<Preferences>("/v1/settings", changes),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
    },
  });
}

export function useTraces() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["traces"],
    queryFn: () => requireClient(client).get<TraceSummary[]>("/v1/traces?limit=100"),
    enabled: client !== null,
  });
}

export function useTrace(id: string | null) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["traces", id],
    queryFn: () =>
      requireClient(client).get<TraceDetail>(`/v1/traces/${encodeURIComponent(id ?? "")}`),
    enabled: client !== null && id !== null,
  });
}

export async function sendPerfReport(
  client: EngineClient,
  report: PerfReport,
): Promise<{ saved_as: string }> {
  return client.post<{ saved_as: string }>("/v1/diagnostics/perf", report);
}

// ---------------------------------------------------------------- conversations

export function useConversations(query: string) {
  const client = useEngineStore((s) => s.client);
  const q = query.trim();
  return useQuery({
    queryKey: ["conversations", q],
    queryFn: () =>
      requireClient(client).get<Conversation[]>(
        `/v1/conversations?limit=100${q ? `&q=${encodeURIComponent(q)}` : ""}`,
      ),
    enabled: client !== null,
  });
}

export function useConversation(id: string | null) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["conversations", "detail", id],
    queryFn: () =>
      requireClient(client).get<ConversationDetail>(
        `/v1/conversations/${encodeURIComponent(id ?? "")}`,
      ),
    enabled: client !== null && id !== null,
  });
}

export function useRenameConversation() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      requireClient(client).patch<Conversation>(`/v1/conversations/${encodeURIComponent(id)}`, {
        title,
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useDeleteConversation() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      requireClient(client).delete<undefined>(`/v1/conversations/${encodeURIComponent(id)}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

// ---------------------------------------------------------------- mémoire

export function useMemory(kind: MemoryKind | null, query: string) {
  const client = useEngineStore((s) => s.client);
  const q = query.trim();
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (q) params.set("q", q);
  const suffix = params.toString();
  return useQuery({
    queryKey: ["memory", kind, q],
    queryFn: () =>
      requireClient(client).get<MemoryItem[]>(`/v1/memory${suffix ? `?${suffix}` : ""}`),
    enabled: client !== null,
  });
}

export function useAddMemory() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (item: { kind: MemoryKind; content: string }) =>
      requireClient(client).post<MemoryItem>("/v1/memory", item),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["memory"] }),
  });
}

export function useUpdateMemory() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...changes
    }: {
      id: number;
      kind?: MemoryKind;
      content?: string;
      pinned?: boolean;
    }) => requireClient(client).patch<MemoryItem>(`/v1/memory/${id}`, changes),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["memory"] }),
  });
}

export function useDeleteMemory() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => requireClient(client).delete<undefined>(`/v1/memory/${id}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["memory"] }),
  });
}

// ---------------------------------------------------------------- modèles

export function useLlmStatus() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["llm", "status"],
    queryFn: () => requireClient(client).get<ProviderStatus[]>("/v1/llm/status"),
    enabled: client !== null,
  });
}

export function useLlmModels() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["llm", "models"],
    queryFn: () => requireClient(client).get<ModelInfo[]>("/v1/llm/models"),
    enabled: client !== null,
    staleTime: 60_000,
  });
}
