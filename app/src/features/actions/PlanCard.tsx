import { AlertDialog } from "radix-ui";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  CircleDashed,
  LoaderCircle,
  MinusCircle,
  ShieldAlert,
  Square,
  X,
  XCircle,
} from "lucide-react";
import { useId, useState } from "react";

import { Button } from "../../components/Button";
import confirmStyles from "../../components/ConfirmDialog.module.css";
import { describeError } from "../../lib/engine/client";
import { useDecidePlan, usePlan, useStopPlan } from "../../lib/engine/queries";
import type { Plan, PlanStep, StepStatus } from "../../lib/engine/types";
import { formatRelative } from "../../lib/format";
import styles from "./Actions.module.css";
import { BrowserLive } from "./BrowserLive";
import { LEVEL_HINT, LEVEL_NAME, PLAN_STATUS, STEP_STATUS } from "./levels";

function StepIcon({ status }: { status: StepStatus }) {
  const label = STEP_STATUS[status];
  if (status === "done") return <Check className={styles.stepDone} role="img" aria-label={label} />;
  if (status === "failed")
    return <XCircle className={styles.stepFailed} role="img" aria-label={label} />;
  if (status === "running")
    return <LoaderCircle className={styles.stepRunning} role="img" aria-label={label} />;
  if (status === "skipped")
    return <MinusCircle className={styles.stepSkipped} role="img" aria-label={label} />;
  return <CircleDashed className={styles.stepPending} role="img" aria-label={label} />;
}

export function LevelBadge({ level }: { level: 1 | 2 | 3 }) {
  return (
    <span className={styles.level} data-level={level} title={LEVEL_HINT[level]}>
      Niveau {level} · {LEVEL_NAME[level]}
    </span>
  );
}

function StepItem({ step }: { step: PlanStep }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const args = Object.entries(step.arguments);
  return (
    <li className={styles.step} data-status={step.status}>
      <span className={styles.stepNumber} aria-hidden="true">
        {step.position}
      </span>
      <div className={styles.stepBody}>
        <p className={styles.stepText}>
          <span className="visually-hidden">Étape {step.position} : </span>
          {step.description}
        </p>
        <p className={styles.stepWhy}>{step.why}</p>
        {step.error && <p className={styles.stepError}>{step.error}</p>}
        <button
          type="button"
          className={styles.detailsToggle}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => {
            setOpen((v) => !v);
          }}
        >
          Détails
          <ChevronDown className={styles.chevron} data-open={open} aria-hidden="true" />
        </button>
        {open && (
          <dl id={panelId} className={styles.args}>
            <div>
              <dt>outil</dt>
              <dd>
                <code>{step.tool}</code>
              </dd>
            </div>
            {args.map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
              </div>
            ))}
            {step.result && (
              <div>
                <dt>résultat</dt>
                <dd className={styles.result}>{step.result}</dd>
              </div>
            )}
          </dl>
        )}
      </div>
      <div className={styles.stepSide}>
        <LevelBadge level={step.level} />
        <StepIcon status={step.status} />
      </div>
    </li>
  );
}

/** Valider un plan de niveau 3 : une seconde confirmation, explicite. */
function DestructiveApprove({ plan, onConfirm }: { plan: Plan; onConfirm: () => void }) {
  const destructive = plan.steps.filter((s) => s.level === 3);
  return (
    <AlertDialog.Root>
      <AlertDialog.Trigger asChild>
        <Button variant="danger" icon={<ShieldAlert />}>
          Valider…
        </Button>
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className={confirmStyles.overlay} />
        <AlertDialog.Content className={confirmStyles.dialog}>
          <ShieldAlert className={confirmStyles.icon} aria-hidden="true" />
          <AlertDialog.Title className={confirmStyles.title}>
            Confirmer une action destructrice
          </AlertDialog.Title>
          <AlertDialog.Description className={confirmStyles.text}>
            Ce plan va {destructive.map((s) => s.description.toLowerCase()).join(", puis ")}.
            C&apos;est ta seconde confirmation : sans elle, rien n&apos;est fait.
          </AlertDialog.Description>
          <div className={confirmStyles.actions}>
            <AlertDialog.Cancel asChild>
              <Button>Annuler</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button variant="danger" onClick={onConfirm}>
                Oui, exécuter
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

export function PlanView({
  plan,
  compact = false,
  showSynthesis = true,
}: {
  plan: Plan;
  compact?: boolean;
  /** Dans une conversation, le compte rendu suit en message : la carte ne le répète pas. */
  showSynthesis?: boolean;
}) {
  const decide = useDecidePlan();
  const stop = useStopPlan();
  const titleId = useId();
  const proposed = plan.status === "proposed";
  const running = plan.status === "approved" || plan.status === "running";
  const browsing = plan.steps.some((step) => step.tool.startsWith("navigateur_"));
  const approve = (doubleConfirm: boolean) => {
    decide.mutate({ id: plan.id, decision: "approve", doubleConfirm });
  };
  return (
    <article className={styles.plan} data-status={plan.status} aria-labelledby={titleId}>
      <header className={styles.planHead}>
        <LevelBadge level={plan.max_level} />
        <span className={styles.planStatus} data-status={plan.status} role="status">
          {PLAN_STATUS[plan.status]}
        </span>
        <span className={styles.planTime}>{formatRelative(plan.created_at)}</span>
      </header>
      <h3 id={titleId} className={styles.planTitle}>
        {plan.title}
      </h3>
      {!compact && plan.request && (
        <p className={styles.request}>Ta demande : « {plan.request} »</p>
      )}
      {plan.tainted && proposed && (
        <p className={styles.tainted} role="note">
          <AlertTriangle aria-hidden="true" />
          Proposé après la lecture d&apos;un contenu externe (page web, fichier). Vérifie que ces
          étapes correspondent bien à ce que tu as demandé.
        </p>
      )}
      <ol className={styles.steps} aria-label="Étapes du plan">
        {plan.steps.map((step) => (
          <StepItem key={step.position} step={step} />
        ))}
      </ol>
      {running && browsing && <BrowserLive />}
      {showSynthesis &&
        plan.result &&
        (plan.status === "done" || plan.status === "failed" || plan.status === "stopped") && (
          <p className={styles.synthesis}>{plan.result}</p>
        )}
      {stop.isError && (
        <p className={styles.decideError} role="alert">
          {describeError(stop.error)}
        </p>
      )}
      {running && (
        <div className={styles.decision} role="group" aria-label="Plan en cours">
          <Button
            icon={<Square />}
            busy={stop.isPending}
            disabled={stop.isSuccess}
            onClick={() => {
              stop.mutate(plan.id);
            }}
          >
            {stop.isSuccess ? "Arrêt après cette étape" : "Arrêter"}
          </Button>
        </div>
      )}
      {decide.isError && (
        <p className={styles.decideError} role="alert">
          {describeError(decide.error)}
        </p>
      )}
      {proposed && (
        <div className={styles.decision} role="group" aria-label="Ta décision">
          <Button
            icon={<X />}
            busy={decide.isPending}
            onClick={() => {
              decide.mutate({ id: plan.id, decision: "refuse" });
            }}
          >
            Refuser
          </Button>
          {plan.max_level >= 3 ? (
            <DestructiveApprove
              plan={plan}
              onConfirm={() => {
                approve(true);
              }}
            />
          ) : (
            <Button
              variant="primary"
              icon={<Check />}
              busy={decide.isPending}
              onClick={() => {
                approve(false);
              }}
            >
              Valider
            </Button>
          )}
        </div>
      )}
    </article>
  );
}

/** Carte d'un plan dans la conversation : se met à jour à chaque étape. */
export function PlanCard({ id, showSynthesis = true }: { id: string; showSynthesis?: boolean }) {
  const plan = usePlan(id);
  if (plan.isPending)
    return (
      <p className={styles.planLoading} role="status">
        Chargement du plan…
      </p>
    );
  if (plan.isError)
    return (
      <p className={styles.decideError} role="alert">
        Plan illisible : {describeError(plan.error)}
      </p>
    );
  return <PlanView plan={plan.data} compact showSynthesis={showSynthesis} />;
}
