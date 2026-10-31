// Automatisations, intégrations (Google, Telegram) et briefing.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useEngineStore } from "../store";
import type {
  Automation,
  AutomationDraft,
  AutomationRun,
  Integration,
  TelegramStatus,
} from "../types";
import { requireClient } from "./shared";

export function useAutomations() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["automations"],
    queryFn: () => requireClient(client).get<Automation[]>("/v1/automations"),
    enabled: client !== null,
  });
}

export function useAutomationEvents() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["automations", "events"],
    queryFn: () =>
      requireClient(client).get<{ type: string; label: string }[]>("/v1/automations/events"),
    enabled: client !== null,
    staleTime: 600_000,
  });
}

export function useAutomationRuns(id: string, enabled: boolean) {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["automations", "runs", id],
    queryFn: () =>
      requireClient(client).get<AutomationRun[]>(
        `/v1/automations/${encodeURIComponent(id)}/runs?limit=10`,
      ),
    enabled: client !== null && enabled,
  });
}

export function useSaveAutomation() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, draft }: { id?: string; draft: AutomationDraft }) =>
      id
        ? requireClient(client).patch<Automation>(
            `/v1/automations/${encodeURIComponent(id)}`,
            draft,
          )
        : requireClient(client).post<Automation>("/v1/automations", draft),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["automations"] }),
  });
}

export function useToggleAutomation() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      requireClient(client).patch<Automation>(`/v1/automations/${encodeURIComponent(id)}`, {
        enabled,
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["automations"] }),
  });
}

export function useDeleteAutomation() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      requireClient(client).delete<undefined>(`/v1/automations/${encodeURIComponent(id)}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["automations"] }),
  });
}

export function useRunAutomation() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      requireClient(client).post<AutomationRun>(`/v1/automations/${encodeURIComponent(id)}/run`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["automations"] }),
  });
}

// ---------------------------------------------------------------- intégrations et téléphone

export function useIntegrations() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["integrations"],
    queryFn: () => requireClient(client).get<Integration[]>("/v1/integrations"),
    enabled: client !== null,
    refetchInterval: (query) =>
      query.state.data?.some((i) => i.status === "connexion") ? 2000 : false,
  });
}

export function useReconnectIntegration() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      requireClient(client).post<Integration[]>(
        `/v1/integrations/${encodeURIComponent(name)}/reconnect`,
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });
}

export function useGoogleAccount() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    /** « connect » rend l'adresse de la page de consentement de Google. */
    mutationFn: async (action: "connect" | "disconnect"): Promise<string | null> => {
      if (action === "connect") {
        const { url } = await requireClient(client).post<{ url: string }>(
          "/v1/integrations/google/connect",
        );
        return url;
      }
      await requireClient(client).post<Integration[]>("/v1/integrations/google/disconnect");
      return null;
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });
}

export function useTelegram() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["telegram"],
    queryFn: () => requireClient(client).get<TelegramStatus>("/v1/telegram"),
    enabled: client !== null,
    refetchInterval: 30_000,
  });
}

export function useStartBriefing() {
  const client = useEngineStore((s) => s.client);
  return useMutation({
    mutationFn: (force: boolean) =>
      requireClient(client).post<{ briefing: string | null }>("/v1/session", { force }),
  });
}

// ---------------------------------------------------------------- skills
