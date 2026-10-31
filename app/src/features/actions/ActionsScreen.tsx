import { PageHeader } from "../../components/PageHeader";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import { usePlans } from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { Plan } from "../../lib/engine/types";
import styles from "./Actions.module.css";
import { PlanView } from "./PlanCard";

function PlanList({ plans, label }: { plans: Plan[]; label: string }) {
  return (
    <ul className={styles.plans} aria-label={label}>
      {plans.map((plan) => (
        <li key={plan.id}>
          <PlanView plan={plan} />
        </li>
      ))}
    </ul>
  );
}

export function ActionsScreen() {
  const plans = usePlans("all");
  const online = useEngineOnline();

  let body;
  if (!online && !plans.data) body = <OfflineState what="La liste des actions" />;
  else if (plans.isPending) body = <LoadingState label="Lecture des plans…" />;
  else if (plans.isError)
    body = (
      <ErrorState
        message={describeError(plans.error)}
        onRetry={() => {
          void plans.refetch();
        }}
      />
    );
  else {
    const waiting = plans.data.filter((p) => p.status === "proposed");
    const active = plans.data.filter((p) => p.status === "approved" || p.status === "running");
    const past = plans.data.filter(
      (p) =>
        p.status === "done" ||
        p.status === "failed" ||
        p.status === "refused" ||
        p.status === "stopped",
    );
    body = (
      <>
        <section className={styles.section} aria-labelledby="a-valider">
          <h2 id="a-valider" className={styles.sectionTitle}>
            À valider{waiting.length > 0 ? ` (${waiting.length})` : ""}
          </h2>
          {waiting.length === 0 ? (
            <EmptyState title="Rien n'attend ta décision">
              Quand Jarvis veut agir pour toi (cliquer, écrire, supprimer), il te propose un plan
              ici. Lire une page ou un fichier ne demande pas de validation.
            </EmptyState>
          ) : (
            <PlanList plans={waiting} label="Plans à valider" />
          )}
        </section>
        {active.length > 0 && (
          <section className={styles.section} aria-labelledby="en-cours">
            <h2 id="en-cours" className={styles.sectionTitle}>
              En cours
            </h2>
            <PlanList plans={active} label="Plans en cours" />
          </section>
        )}
        {past.length > 0 && (
          <section className={styles.section} aria-labelledby="passes">
            <h2 id="passes" className={styles.sectionTitle}>
              Déjà décidés
            </h2>
            <PlanList plans={past} label="Plans déjà décidés" />
          </section>
        )}
      </>
    );
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Actions à valider"
        description="Chaque plan dit ce qui va se passer, sur quoi et à quel niveau. Rien n'est fait sans ta décision."
      />
      {body}
    </div>
  );
}
