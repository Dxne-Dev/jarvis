import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { EngineClient } from "./client";
import { useEngineStore } from "./store";
import type {
  AuditPage,
  BrowserGrant,
  BrowserState,
  CartesiaVoice,
  CheckResult,
  Conversation,
  ConversationDetail,
  EngineStatus,
  MemoryItem,
  MemoryKind,
  ModelInfo,
  ProviderStatus,
  PerfReport,
  Plan,
  Preferences,
  SecretStatus,
  ToolInfo,
  TraceDetail,
  TraceSummary,
  VoiceDevices,
  VoiceStatus,
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

// ---------------------------------------------------------------- voix

export function useVoiceStatus() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["voice", "status"],
    queryFn: () => requireClient(client).get<VoiceStatus>("/v1/voice/status"),
    enabled: client !== null,
  });
}

export function useVoiceDevices(enabled: boolean) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["voice", "devices"],
    queryFn: () => requireClient(client).get<VoiceDevices>("/v1/voice/devices"),
    enabled: client !== null && enabled,
    staleTime: 30_000,
  });
}

export function useCartesiaVoices(enabled: boolean) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["voice", "voices"],
    queryFn: () => requireClient(client).get<CartesiaVoice[]>("/v1/voice/voices"),
    enabled: client !== null && enabled,
    staleTime: 600_000,
  });
}

/** Parler sans dire « Hey Jarvis » (bouton micro, raccourci clavier). */
export function useVoiceListen() {
  const client = useEngineStore((s) => s.client);
  return useMutation({
    mutationFn: () => requireClient(client).post<undefined>("/v1/voice/listen"),
  });
}

export function useVoiceStop() {
  const client = useEngineStore((s) => s.client);
  return useMutation({
    mutationFn: () => requireClient(client).post<undefined>("/v1/voice/stop"),
  });
}

// ---------------------------------------------------------------- Jarvis agit

export type PlanFilter = "pending" | "active" | "all";

export function usePlans(filter: PlanFilter) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["plans", filter],
    queryFn: () => requireClient(client).get<Plan[]>(`/v1/plans?status=${filter}&limit=100`),
    enabled: client !== null,
  });
}

export function usePlan(id: string) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["plans", "detail", id],
    queryFn: () => requireClient(client).get<Plan>(`/v1/plans/${encodeURIComponent(id)}`),
    enabled: client !== null,
  });
}

export function useDecidePlan() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      decision,
      doubleConfirm = false,
    }: {
      id: string;
      decision: "approve" | "refuse";
      doubleConfirm?: boolean;
    }) =>
      decision === "approve"
        ? requireClient(client).post<Plan>(`/v1/plans/${encodeURIComponent(id)}/approve`, {
            double_confirm: doubleConfirm,
          })
        : requireClient(client).post<Plan>(`/v1/plans/${encodeURIComponent(id)}/refuse`),
    onSuccess: (plan) => {
      queryClient.setQueryData(["plans", "detail", plan.id], plan);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["plans"] }),
  });
}

export function useAudit() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["audit"],
    queryFn: () => requireClient(client).get<AuditPage>("/v1/audit?limit=200"),
    enabled: client !== null,
  });
}

export function useVerifyAudit() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      requireClient(client).post<{ ok: boolean; count: number; broken_at: number | null }>(
        "/v1/audit/verify",
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["audit"] }),
  });
}

export function useTools() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["tools"],
    queryFn: () => requireClient(client).get<ToolInfo[]>("/v1/tools"),
    enabled: client !== null,
    staleTime: 300_000,
  });
}

export function useBrowser() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["browser"],
    queryFn: () => requireClient(client).get<BrowserState>("/v1/browser"),
    enabled: client !== null,
  });
}

export function useImportCookies() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { source: string; domain: string }) =>
      requireClient(client).post<BrowserGrant>("/v1/browser/cookies", body),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["browser"] }),
  });
}

export function useRevokeCookies() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (domain: string) =>
      requireClient(client).delete<undefined>(`/v1/browser/cookies/${encodeURIComponent(domain)}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["browser"] }),
  });
}

export function useBrowserLogin() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ action, url }: { action: "start" | "finish"; url?: string }) =>
      action === "start"
        ? requireClient(client).post<{ domain: string }>("/v1/browser/login", { url })
        : requireClient(client).post<BrowserGrant | null>("/v1/browser/login/finish"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["browser"] }),
  });
}
