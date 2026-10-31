// La voix : état, micros et haut-parleurs, voix Cartesia, écoute.

import { useMutation, useQuery } from "@tanstack/react-query";

import { useEngineStore } from "../store";
import type { CartesiaVoice, VoiceDevices, VoiceStatus } from "../types";
import { requireClient } from "./shared";

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
