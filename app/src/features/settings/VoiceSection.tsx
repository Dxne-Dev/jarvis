import { useId } from "react";

import { describeError } from "../../lib/engine/client";
import {
  useCartesiaVoices,
  usePreferences,
  useUpdatePreferences,
  useVoiceDevices,
  useVoiceStatus,
} from "../../lib/engine/queries";
import type { Preferences, VoiceStatus } from "../../lib/engine/types";
import { Choice, PreferenceSwitch } from "./PreferenceControls";
import styles from "./SettingsScreen.module.css";

const STATE_LABEL: Record<VoiceStatus["state"], string> = {
  off: "Coupée",
  starting: "Préparation…",
  idle: "À l'écoute de « Hey Jarvis »",
  listening: "J'écoute",
  thinking: "Je réfléchis",
  speaking: "Je parle",
  error: "Indisponible",
};

const MODEL_LABEL: Record<string, string> = {
  reveil: "Mot de réveil",
  transcription: "Transcription",
  voix_locale: "Voix locale",
};

function statusTone(status: VoiceStatus): "ok" | "down" | "idle" {
  if (status.error || status.state === "error") return "down";
  if (status.state === "off" || status.state === "starting") return "idle";
  return "ok";
}

function VoiceState() {
  const status = useVoiceStatus();
  if (!status.data?.state) return null;
  const data = status.data;
  const models = Object.entries(data.models)
    .map(([key, value]) => `${MODEL_LABEL[key] ?? key} : ${value}`)
    .join(" · ");
  return (
    <div className={styles.voiceStatus} data-tone={statusTone(data)} role="status">
      <span className={styles.voiceDot} aria-hidden="true" />
      <div className={styles.voiceStatusText}>
        <p className={styles.voiceStatusTitle}>{STATE_LABEL[data.state]}</p>
        {data.error && <p className={styles.radioHint}>{data.error}</p>}
        {models && <p className={styles.radioHint}>{models}</p>}
        <p className={styles.radioHint}>
          {data.echo_cancel
            ? "Annulation d'écho active : tu peux couper Jarvis en parlant."
            : "Sans annulation d'écho : redis « Hey Jarvis » pour couper Jarvis."}
          {data.last_latency_ms !== null &&
            ` Dernière réponse parlée en ${(data.last_latency_ms / 1000).toFixed(1).replace(".", ",")} s.`}
        </p>
        {data.tts_fallback && (
          <p className={styles.radioHint}>Voix locale utilisée : Cartesia ne répondait pas.</p>
        )}
      </div>
    </div>
  );
}

function DeviceSelect({
  name,
  label,
  options,
}: {
  name: "voice_input_device" | "voice_output_device" | "voice_name";
  label: string;
  options: { value: string; label: string }[];
}) {
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const id = useId();
  const value = preferences.data?.[name] ?? "";
  const known = options.some((o) => o.value === value);
  return (
    <div className={styles.routingRow}>
      <label htmlFor={id} className={styles.routingLabel}>
        <span>{label}</span>
      </label>
      <select
        id={id}
        className={`${styles.input} ${styles.select}`}
        value={value}
        disabled={!preferences.data || update.isPending}
        onChange={(event) => {
          const next = event.target.value;
          const change: Partial<Preferences> =
            name === "voice_name" ? { voice_name: next } : { [name]: next || null };
          update.mutate(change);
        }}
      >
        {name !== "voice_name" && <option value="">Par défaut du système</option>}
        {!known && value && <option value={value}>{value}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function VoiceSection() {
  const preferences = usePreferences();
  const enabled = preferences.data?.voice_enabled ?? false;
  const devices = useVoiceDevices(enabled);
  const voices = useCartesiaVoices(enabled && preferences.data?.voice_engine !== "piper");
  return (
    <>
      <VoiceState />
      <PreferenceSwitch
        name="voice_enabled"
        label="Parler à Jarvis"
        hint="« Hey Jarvis » est reconnu sur ta machine : aucun son n'en sort avant."
      />
      {enabled && (
        <>
          <Choice
            name="wake_sensitivity"
            label="Sensibilité du mot de réveil"
            options={[
              { value: "basse", label: "Basse", hint: "Moins de faux réveils." },
              {
                value: "normale",
                label: "Normale",
                hint: "Un doute est vérifié par transcription locale.",
              },
              { value: "haute", label: "Haute", hint: "Pour une voix lointaine ou un accent." },
            ]}
          />
          <Choice
            name="voice_engine"
            label="Voix de Jarvis"
            options={[
              {
                value: "auto",
                label: "Cartesia",
                hint: "Naturelle ; la voix locale prend le relais hors ligne.",
              },
              { value: "piper", label: "Locale (Piper)", hint: "Tout reste sur la machine." },
            ]}
          />
          {preferences.data?.voice_engine !== "piper" && voices.data && voices.data.length > 0 && (
            <DeviceSelect
              name="voice_name"
              label="Timbre"
              options={voices.data.map((v) => ({
                value: v.id,
                label: v.description ? `${v.name} — ${v.description}` : v.name,
              }))}
            />
          )}
          {devices.data && (
            <>
              <DeviceSelect
                name="voice_input_device"
                label="Micro"
                options={devices.data.inputs.map((d) => ({ value: d.name, label: d.label }))}
              />
              <DeviceSelect
                name="voice_output_device"
                label="Haut-parleur"
                options={devices.data.outputs.map((d) => ({ value: d.name, label: d.label }))}
              />
            </>
          )}
          {devices.isError && (
            <p className={styles.ko} role="alert">
              {describeError(devices.error)}
            </p>
          )}
          <PreferenceSwitch
            name="voice_follow_up"
            label="Continuer sans redire « Hey Jarvis »"
            hint="Après une réponse, Jarvis écoute encore six secondes."
          />
          <PreferenceSwitch
            name="voice_barge_in"
            label="Couper Jarvis en parlant"
            hint="Avec l'annulation d'écho ou un casque."
          />
          <PreferenceSwitch
            name="voice_headset"
            label="J'utilise un casque"
            hint="Jarvis ne peut pas s'entendre : la coupure à la voix reste possible."
          />
        </>
      )}
    </>
  );
}
