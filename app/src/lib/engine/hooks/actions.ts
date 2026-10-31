// Plans, journal des actions, outils, partage d'écran et navigateur de Jarvis.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useEngineStore } from "../store";
import type {
  AuditPage,
  BrowserGrant,
  BrowserState,
  ScreenShareState,
  Plan,
  ToolInfo,
} from "../types";
import { requireClient } from "./shared";

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

/** « Arrêter » : l'étape en cours se termine, les suivantes ne partent pas. */
export function useStopPlan() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      requireClient(client).post<Plan>(`/v1/plans/${encodeURIComponent(id)}/stop`),
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

export function useScreenShare() {
  const client = useEngineStore((s) => s.client);
  return useQuery({
    queryKey: ["screen-share"],
    queryFn: () => requireClient(client).get<ScreenShareState>("/v1/desktop/share"),
    enabled: client !== null,
  });
}

/** Partager l'écran (GNOME demande ton accord la première fois) ou arrêter. */
export function useToggleScreenShare() {
  const client = useEngineStore((s) => s.client);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) =>
      requireClient(client).post<ScreenShareState>(`/v1/desktop/share/${on ? "start" : "stop"}`),
    onSuccess: (state) => {
      queryClient.setQueryData(["screen-share"], state);
    },
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

// ---------------------------------------------------------------- automatisations
