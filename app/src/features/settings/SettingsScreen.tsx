import { RadioGroup } from "radix-ui";
import { useId } from "react";

import { PageHeader } from "../../components/PageHeader";
import { ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  usePreferences,
  useSecrets,
  useStatus,
  useUpdatePreferences,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { Preferences, SecretGroup, SecretStatus } from "../../lib/engine/types";
import { ModelsSection } from "./ModelsSection";
import { SecretRow } from "./SecretRow";
import styles from "./SettingsScreen.module.css";

const GROUPS: { id: SecretGroup; title: string; description: string }[] = [
  { id: "llm", title: "Modèles de langage", description: "Le cerveau de Jarvis." },
  { id: "voice", title: "Voix", description: "Synthèse vocale en ligne." },
  { id: "search", title: "Recherche", description: "Recherche sur le web." },
  { id: "integrations", title: "Intégrations", description: "GitHub, Notion, Google Agenda." },
  { id: "phone", title: "Téléphone", description: "Parler à Jarvis depuis Telegram." },
];

function ProvidersSection() {
  const secrets = useSecrets();
  const status = useStatus();
  const online = useEngineOnline();

  if (!online && !secrets.data) return <OfflineState what="La liste des clés" />;
  if (secrets.isPending) return <LoadingState label="Lecture du trousseau…" />;
  if (secrets.isError) {
    return (
      <ErrorState
        message={describeError(secrets.error)}
        onRetry={() => {
          void secrets.refetch();
        }}
      />
    );
  }

  const keyringError = status.data?.keyring_error ?? null;
  const byGroup = new Map<SecretGroup, SecretStatus[]>();
  for (const secret of secrets.data) {
    byGroup.set(secret.group, [...(byGroup.get(secret.group) ?? []), secret]);
  }

  return (
    <>
      {keyringError && (
        <ErrorState
          title="Trousseau indisponible"
          message={`${keyringError} Les clés ne peuvent pas être enregistrées tant qu'il n'est pas déverrouillé.`}
        />
      )}
      {GROUPS.map((group) => (
        <section key={group.id} className={styles.group} aria-labelledby={`groupe-${group.id}`}>
          <div className={styles.groupHead}>
            <h3 id={`groupe-${group.id}`} className={styles.groupTitle}>
              {group.title}
            </h3>
            <p className={styles.groupDescription}>{group.description}</p>
          </div>
          <ul className={styles.secrets}>
            {(byGroup.get(group.id) ?? []).map((secret) => (
              <SecretRow
                key={secret.name}
                secret={secret}
                disabled={!online || keyringError !== null}
              />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

function Choice<K extends "reduced_motion" | "sphere_quality">({
  name,
  label,
  options,
}: {
  name: K;
  label: string;
  options: { value: Preferences[K]; label: string; hint: string }[];
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
        disabled={!preferences.data || update.isPending}
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

export function SettingsScreen() {
  return (
    <div className={styles.page}>
      <PageHeader
        title="Réglages"
        description="Les clés sont gardées dans le trousseau du système. Une clé enregistrée n'est jamais réaffichée."
      />
      <section className={styles.section} aria-labelledby="fournisseurs">
        <h2 id="fournisseurs" className={styles.sectionTitle}>
          Fournisseurs et clés
        </h2>
        <ProvidersSection />
      </section>
      <section className={styles.section} aria-labelledby="modeles">
        <h2 id="modeles" className={styles.sectionTitle}>
          Modèles
        </h2>
        <ModelsSection />
      </section>
      <section className={styles.section} aria-labelledby="apparence">
        <h2 id="apparence" className={styles.sectionTitle}>
          Apparence
        </h2>
        <Choice
          name="reduced_motion"
          label="Animations"
          options={[
            { value: "system", label: "Comme le système", hint: "Suit le réglage d'Ubuntu." },
            {
              value: "reduce",
              label: "Réduites",
              hint: "Mouvements minimaux, mêmes informations.",
            },
            { value: "full", label: "Complètes", hint: "Toutes les animations." },
          ]}
        />
        <Choice
          name="sphere_quality"
          label="Qualité de la sphère"
          options={[
            { value: "auto", label: "Automatique", hint: "Équilibre fluidité et finesse." },
            { value: "high", label: "Haute", hint: "Plus de points, plus de calcul." },
            { value: "low", label: "Économe", hint: "Pour une machine chargée." },
          ]}
        />
      </section>
    </div>
  );
}
