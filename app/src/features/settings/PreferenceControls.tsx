import { RadioGroup, Switch } from "radix-ui";
import { useId } from "react";

import { describeError } from "../../lib/engine/client";
import { usePreferences, useUpdatePreferences } from "../../lib/engine/queries";
import type { Preferences } from "../../lib/engine/types";
import styles from "./SettingsScreen.module.css";

type ChoiceKey = "reduced_motion" | "sphere_quality" | "wake_sensitivity" | "voice_engine";
type SwitchKey =
  | "learn_from_conversations"
  | "voice_enabled"
  | "voice_follow_up"
  | "voice_barge_in"
  | "voice_headset";

/** Un réglage à choix unique, en boutons radio accessibles. */
export function Choice<K extends ChoiceKey>({
  name,
  label,
  options,
  disabled = false,
}: {
  name: K;
  label: string;
  options: { value: Preferences[K]; label: string; hint: string }[];
  disabled?: boolean;
}) {
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const labelId = useId();
  const value = preferences.data?.[name];
  return (
    <div className={styles.choice}>
      <p id={labelId} className={styles.choiceLabel}>
        {label}
      </p>
      <RadioGroup.Root
        className={styles.radios}
        aria-labelledby={labelId}
        value={value ?? ""}
        disabled={disabled || !preferences.data || update.isPending}
        onValueChange={(next) => {
          update.mutate({ [name]: next });
        }}
      >
        {options.map((option) => (
          <RadioGroup.Item key={option.value} value={option.value} className={styles.radio}>
            <span className={styles.radioDot} aria-hidden="true">
              <RadioGroup.Indicator className={styles.radioIndicator} />
            </span>
            <span className={styles.radioText}>
              <span>{option.label}</span>
              <span className={styles.radioHint}>{option.hint}</span>
            </span>
          </RadioGroup.Item>
        ))}
      </RadioGroup.Root>
      {update.isError && (
        <p className={styles.ko} role="alert">
          {describeError(update.error)}
        </p>
      )}
    </div>
  );
}

/** Un réglage oui/non, en interrupteur. */
export function PreferenceSwitch({
  name,
  label,
  hint,
  disabled = false,
}: {
  name: SwitchKey;
  label: string;
  hint: string;
  disabled?: boolean;
}) {
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const id = useId();
  const checked = preferences.data?.[name] ?? false;
  return (
    <div className={styles.switchRow}>
      <label htmlFor={id} className={styles.routingLabel}>
        <span>{label}</span>
        <span className={styles.radioHint}>{hint}</span>
      </label>
      <Switch.Root
        id={id}
        className={styles.switch}
        checked={checked}
        disabled={disabled || !preferences.data || update.isPending}
        onCheckedChange={(value) => {
          update.mutate({ [name]: value });
        }}
      >
        <Switch.Thumb className={styles.switchThumb} />
      </Switch.Root>
    </div>
  );
}
