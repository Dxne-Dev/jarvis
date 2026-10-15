import { ShieldCheck, ShieldX } from "lucide-react";

import { Button } from "../../components/Button";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import { useAudit, useVerifyAudit } from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { AuditEntry } from "../../lib/engine/types";
import { formatDateTime } from "../../lib/format";
import { LevelBadge } from "../actions/PlanCard";
import styles from "./JournalScreen.module.css";

const ACTOR_LABEL: Record<AuditEntry["actor"], string> = {
  utilisateur: "Toi",
  jarvis: "Jarvis",
  automatisation: "Automatisation",
};

function Integrity({
  ok,
  brokenAt,
  total,
}: {
  ok: boolean | null;
  brokenAt: number | null;
  total: number;
}) {
  const verify = useVerifyAudit();
  const label =
    ok === false
      ? `Chaîne rompue à l'entrée n° ${brokenAt ?? "?"} : une ligne a été modifiée hors de Jarvis.`
      : `${total} entrée${total > 1 ? "s" : ""}, chaîne d'empreintes intacte.`;
  return (
    <div className={styles.integrity} data-ok={ok !== false} role="status">
      {ok === false ? <ShieldX aria-hidden="true" /> : <ShieldCheck aria-hidden="true" />}
      <p>{label}</p>
      <Button
        size="sm"
        busy={verify.isPending}
        onClick={() => {
          verify.mutate();
        }}
      >
        Vérifier maintenant
      </Button>
    </div>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const details = Object.entries(entry.details).filter(([, v]) => v !== null && v !== "");
  return (
    <li className={styles.audit}>
      <div className={styles.auditHead}>
        <LevelBadge level={entry.level} />
        <span className={styles.auditActor}>{ACTOR_LABEL[entry.actor]}</span>
        <time className={styles.rowMeta} dateTime={entry.ts}>
          {formatDateTime(entry.ts)}
        </time>
      </div>
      <p className={styles.auditSummary}>{entry.summary}</p>
      {details.length > 0 && (
        <details className={styles.auditDetails}>
          <summary>Détails</summary>
          <dl className={styles.attributes}>
            <div className={styles.attribute}>
              <dt>action</dt>
              <dd>{entry.action}</dd>
            </div>
            {details.map(([key, value]) => (
              <div key={key} className={styles.attribute}>
                <dt>{key}</dt>
                <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
              </div>
            ))}
            <div className={styles.attribute}>
              <dt>empreinte</dt>
              <dd>
                <code>{entry.hash.slice(0, 16)}…</code>
              </dd>
            </div>
          </dl>
        </details>
      )}
    </li>
  );
}

/** Journal des actions (niveaux 2 et 3) : ajout seul, aucune suppression possible. */
export function AuditPanel() {
  const audit = useAudit();
  const online = useEngineOnline();
  if (!online && !audit.data) return <OfflineState what="Le journal des actions" />;
  if (audit.isPending) return <LoadingState label="Lecture du journal des actions…" />;
  if (audit.isError)
    return (
      <ErrorState
        message={describeError(audit.error)}
        onRetry={() => {
          void audit.refetch();
        }}
      />
    );
  const page = audit.data;
  return (
    <div className={styles.auditPanel}>
      <Integrity ok={page.integrity_ok} brokenAt={page.broken_at} total={page.total} />
      {page.items.length === 0 ? (
        <EmptyState title="Aucune action pour l'instant">
          Chaque action validée (niveau 2 ou 3) et chaque décision sur un plan s&apos;écrit ici,
          sans pouvoir être effacée.
        </EmptyState>
      ) : (
        <ul className={styles.list} aria-label="Actions journalisées">
          {page.items.map((entry) => (
            <AuditRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
    </div>
  );
}
