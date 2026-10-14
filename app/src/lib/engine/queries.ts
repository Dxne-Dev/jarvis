import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { EngineClient } from "./client";
import { useEngineStore } from "./store";
import type {
  CheckResult,
  EngineStatus,
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
