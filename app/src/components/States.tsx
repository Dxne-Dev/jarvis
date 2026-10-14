import { CircleAlert, CloudOff, Inbox, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./Button";
import styles from "./States.module.css";

/** États obligatoires de chaque écran : chargement, vide, erreur, hors ligne, partiel. */

export function LoadingState({ label = "Chargement…" }: { label?: string }) {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      <LoaderCircle className={styles.spin} aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={styles.state}>
      <Inbox aria-hidden="true" />
      <p className={styles.title}>{title}</p>
      {children && <p className={styles.text}>{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Ça n'a pas marché.",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className={`${styles.state} ${styles.error}`} role="alert">
      <CircleAlert aria-hidden="true" />
      <p className={styles.title}>{title}</p>
      <p className={styles.text}>{message}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Réessayer
        </Button>
      )}
    </div>
  );
}

export function OfflineState({ what }: { what: string }) {
  return (
    <div className={styles.state} role="status">
      <CloudOff aria-hidden="true" />
      <p className={styles.title}>Moteur hors ligne</p>
      <p className={styles.text}>
        {what} reviendra dès que le moteur répondra. La reconnexion est automatique.
      </p>
    </div>
  );
}

/** Une partie des données manque : on montre ce qu'on a et on le dit. */
export function PartialNotice({ children }: { children: ReactNode }) {
  return (
    <p className={styles.partial} role="note">
      <CircleAlert aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}
