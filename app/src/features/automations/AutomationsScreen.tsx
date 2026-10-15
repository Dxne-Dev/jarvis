import { Switch } from "radix-ui";
import { CalendarClock, ChevronDown, Play, Plus, Zap } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";

import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useAutomationRuns,
  useAutomations,
  useDeleteAutomation,
  useRunAutomation,
  useToggleAutomation,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { Automation, AutomationRun } from "../../lib/engine/types";
import { formatMoment, formatRelative } from "../../lib/format";
import { AutomationForm } from "./AutomationForm";
import styles from "./Automations.module.css";

const LAST_STATUS: Record<NonNullable<Automation["last_status"]>, string> = {
  ok: "réussi",
  failed: "en échec",
  missed: "manquée (Jarvis était éteint)",
  running: "en cours",
};

const RUN_STATUS: Record<AutomationRun["status"], string> = {
  pending: "en attente",
  running: "en cours",
  done: "faite",
  failed: "en échec",
};

const REASON: Record<NonNullable<AutomationRun["reason"]>, string> = {
  horaire: "à l'heure dite",
  evenement: "sur un événement",
  manuel: "lancée à la main",
};

function Runs({ automation }: { automation: Automation }) {
  const runs = useAutomationRuns(automation.id, true);
  if (runs.isPending) return <p className={styles.meta}>Lecture de l&apos;historique…</p>;
  if (runs.isError) return <p className={styles.error}>{describeError(runs.error)}</p>;
  if (runs.data.length === 0) return <p className={styles.meta}>Pas encore de passage.</p>;
  return (
    <ul className={styles.runs} aria-label={`Passages de ${automation.name}`}>
      {runs.data.map((run) => (
        <li key={run.id} className={styles.run} data-status={run.status}>
          <p className={styles.runHead}>
            {formatMoment(run.created_at)}
            {run.reason ? ` · ${REASON[run.reason]}` : ""}
            {" · "}
            <span className={styles.runStatus}>{RUN_STATUS[run.status]}</span>
          </p>
          {run.summary && <p className={styles.runSummary}>{run.summary}</p>}
          {run.error && <p className={styles.error}>{run.error}</p>}
          {run.plans.length > 0 && (
            <p className={styles.meta}>
              <Link to="/actions">
                {run.plans.length === 1
                  ? "Une action attend ta validation"
                  : `${run.plans.length} actions attendent ta validation`}
              </Link>
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function AutomationCard({ automation, online }: { automation: Automation; online: boolean }) {
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState(false);
  const toggle = useToggleAutomation();
  const remove = useDeleteAutomation();
  const run = useRunAutomation();
  const titleId = useId();
  const historyId = useId();
  const error = toggle.error ?? remove.error ?? run.error;
  if (editing) {
    return (
      <AutomationForm
        automation={automation}
        onDone={() => {
          setEditing(false);
        }}
      />
    );
  }
  const Icon = automation.trigger.type === "horaire" ? CalendarClock : Zap;
  return (
    <article className={styles.card} data-enabled={automation.enabled} aria-labelledby={titleId}>
      <header className={styles.cardHead}>
        <Icon className={styles.cardIcon} aria-hidden="true" />
        <h2 id={titleId} className={styles.cardTitle}>
          {automation.name}
        </h2>
        <label className={styles.switchLabel}>
          <span>{automation.enabled ? "Active" : "Désactivée"}</span>
          <Switch.Root
            className={styles.switch}
            checked={automation.enabled}
            disabled={!online || toggle.isPending}
            aria-label={`${automation.enabled ? "Désactiver" : "Activer"} ${automation.name}`}
            onCheckedChange={(enabled) => {
              toggle.mutate({ id: automation.id, enabled });
            }}
          >
            <Switch.Thumb className={styles.switchThumb} />
          </Switch.Root>
        </label>
      </header>
      <p className={styles.when}>{automation.when}</p>
      <p className={styles.what}>{automation.what}</p>
      <p className={styles.meta}>
        {automation.enabled && automation.next_run_at
          ? `Prochaine fois : ${formatMoment(automation.next_run_at)}`
          : automation.trigger.type === "evenement" && automation.enabled
            ? "Attend l'événement"
            : "Ne tournera plus"}
        {automation.last_run_at &&
          ` · Dernier passage : ${formatRelative(automation.last_run_at)}${
            automation.last_status ? ` (${LAST_STATUS[automation.last_status]})` : ""
          }`}
        {automation.last_status === "missed" &&
          !automation.last_run_at &&
          " · Dernière échéance manquée"}
        {automation.run_count > 1 && ` · ${automation.run_count} passages en tout`}
        {automation.created_by === "jarvis" && " · Créée par Jarvis à ta demande"}
      </p>
      {error && (
        <p className={styles.error} role="alert">
          {describeError(error)}
        </p>
      )}
      {run.isSuccess && (
        <p className={styles.meta} role="status">
          Lancée : le résultat arrive dans les notifications.
        </p>
      )}
      <div className={styles.cardActions}>
        <Button
          size="sm"
          icon={<Play />}
          disabled={!online}
          busy={run.isPending}
          onClick={() => {
            run.mutate(automation.id);
          }}
        >
          Lancer maintenant
        </Button>
        <Button
          size="sm"
          disabled={!online}
          onClick={() => {
            setEditing(true);
          }}
        >
          Modifier
        </Button>
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={history}
          aria-controls={historyId}
          onClick={() => {
            setHistory((v) => !v);
          }}
        >
          Historique
          <ChevronDown className={styles.chevron} data-open={history} aria-hidden="true" />
        </Button>
        <ConfirmDialog
          trigger={
            <Button size="sm" variant="ghost" disabled={!online}>
              Supprimer
            </Button>
          }
          title={`Supprimer « ${automation.name} » ?`}
          description="Elle ne tournera plus et son historique sera effacé. Les conversations qu'elle a écrites restent dans l'historique."
          confirmLabel="Supprimer"
          cancelLabel="Garder"
          onConfirm={() => {
            remove.mutate(automation.id);
          }}
        />
      </div>
      {history && (
        <div id={historyId}>
          <Runs automation={automation} />
        </div>
      )}
    </article>
  );
}

export function AutomationsScreen() {
  const automations = useAutomations();
  const online = useEngineOnline();
  const [creating, setCreating] = useState(false);

  let body;
  if (!online && !automations.data) body = <OfflineState what="La liste des automatisations" />;
  else if (automations.isPending) body = <LoadingState label="Lecture des automatisations…" />;
  else if (automations.isError)
    body = (
      <ErrorState
        message={describeError(automations.error)}
        onRetry={() => {
          void automations.refetch();
        }}
      />
    );
  else if (automations.data.length === 0 && !creating)
    body = (
      <EmptyState
        title="Aucune automatisation"
        action={
          <Button
            variant="primary"
            icon={<Plus />}
            onClick={() => {
              setCreating(true);
            }}
          >
            Créer une automatisation
          </Button>
        }
      >
        Dis par exemple « Hey Jarvis, rappelle-moi tous les matins à 8 h de boire de l&apos;eau »,
        ou crée-la ici.
      </EmptyState>
    );
  else
    body = (
      <ul className={styles.list} aria-label="Automatisations">
        {automations.data.map((automation) => (
          <li key={automation.id}>
            <AutomationCard automation={automation} online={online} />
          </li>
        ))}
      </ul>
    );

  return (
    <div className={styles.page}>
      <PageHeader
        title="Automatisations"
        description="Rappels et tâches que Jarvis fait pour toi, à l'heure dite ou quand quelque chose arrive. Elles ne font jamais seules une action : elles la préparent et te préviennent."
        actions={
          !creating && (automations.data?.length ?? 0) > 0 ? (
            <Button
              variant="primary"
              icon={<Plus />}
              disabled={!online}
              onClick={() => {
                setCreating(true);
              }}
            >
              Nouvelle automatisation
            </Button>
          ) : undefined
        }
      />
      {creating && (
        <AutomationForm
          onDone={() => {
            setCreating(false);
          }}
        />
      )}
      {body}
    </div>
  );
}
