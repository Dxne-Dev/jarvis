import { AlertDialog } from "radix-ui";
import { CheckCircle2, KeyRound, ShieldAlert, XCircle } from "lucide-react";
import { useId, useState, type SyntheticEvent } from "react";

import { Button } from "../../components/Button";
import { describeError } from "../../lib/engine/client";
import { useCheckSecret, useDeleteSecret, useSaveSecret } from "../../lib/engine/queries";
import type { SecretStatus } from "../../lib/engine/types";
import { formatDuration, formatRelative } from "../../lib/format";
import dialogStyles from "./SecretRow.module.css";
import styles from "./SettingsScreen.module.css";

const SOURCE_LABEL = { env: "importée du .env", ui: "saisie ici", generated: "générée" } as const;

export function SecretRow({ secret, disabled }: { secret: SecretStatus; disabled: boolean }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const save = useSaveSecret();
  const remove = useDeleteSecret();
  const check = useCheckSecret();
  const inputId = useId();
  const statusId = useId();

  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!value.trim()) return;
    save.mutate(
      { name: secret.name, value },
      {
        onSuccess: () => {
          setValue("");
          setEditing(false);
          check.mutate(secret.name);
        },
      },
    );
  };

  const lastCheck =
    secret.last_check_ok === null ? null : (
      <span className={secret.last_check_ok ? styles.ok : styles.ko}>
        {secret.last_check_ok ? (
          <CheckCircle2 aria-hidden="true" />
        ) : (
          <XCircle aria-hidden="true" />
        )}
        {secret.last_check_ok ? "Vérifiée" : "Refusée"}
        {secret.last_check_detail ? ` — ${secret.last_check_detail}` : ""}
        {secret.last_check_latency_ms !== null && (
          <span className={styles.meta}> · {formatDuration(secret.last_check_latency_ms)}</span>
        )}
        {secret.last_check_at && (
          <span className={styles.meta}> · {formatRelative(secret.last_check_at)}</span>
        )}
      </span>
    );

  const error = save.error ?? remove.error ?? check.error;

  return (
    <li className={styles.secret} aria-describedby={statusId}>
      <div className={styles.secretHead}>
        <KeyRound className={styles.secretIcon} aria-hidden="true" />
        <div className={styles.secretText}>
          <p className={styles.secretLabel}>{secret.label}</p>
          <p className={styles.secretHelp}>
            {secret.help} <code className={styles.code}>{secret.name}</code>
          </p>
        </div>
        <p id={statusId} className={styles.secretStatus} data-configured={secret.configured}>
          {secret.configured
            ? `Configurée${secret.source ? `, ${SOURCE_LABEL[secret.source]}` : ""}`
            : "Non configurée"}
        </p>
        {!editing && (
          <div className={styles.actions}>
            <Button
              size="sm"
              variant="secondary"
              disabled={disabled}
              onClick={() => {
                setEditing(true);
              }}
            >
              {secret.configured ? "Remplacer" : "Ajouter"}
            </Button>
            {secret.configured && (
              <Button
                size="sm"
                disabled={disabled}
                busy={check.isPending}
                onClick={() => {
                  check.mutate(secret.name);
                }}
              >
                Vérifier
              </Button>
            )}
            {secret.configured && (
              <AlertDialog.Root>
                <AlertDialog.Trigger asChild>
                  <Button size="sm" variant="ghost" disabled={disabled}>
                    Supprimer
                  </Button>
                </AlertDialog.Trigger>
                <AlertDialog.Portal>
                  <AlertDialog.Overlay className={dialogStyles.overlay} />
                  <AlertDialog.Content className={dialogStyles.dialog}>
                    <ShieldAlert className={dialogStyles.dialogIcon} aria-hidden="true" />
                    <AlertDialog.Title className={dialogStyles.dialogTitle}>
                      Supprimer la clé {secret.label} ?
                    </AlertDialog.Title>
                    <AlertDialog.Description className={dialogStyles.dialogText}>
                      Elle sera retirée du trousseau du système. Les fonctions qui en dépendent
                      s'arrêteront jusqu'à ce que tu en saisisses une nouvelle.
                    </AlertDialog.Description>
                    <div className={dialogStyles.dialogActions}>
                      <AlertDialog.Cancel asChild>
                        <Button>Garder la clé</Button>
                      </AlertDialog.Cancel>
                      <AlertDialog.Action asChild>
                        <Button
                          variant="danger"
                          onClick={() => {
                            remove.mutate(secret.name);
                          }}
                        >
                          Supprimer
                        </Button>
                      </AlertDialog.Action>
                    </div>
                  </AlertDialog.Content>
                </AlertDialog.Portal>
              </AlertDialog.Root>
            )}
          </div>
        )}
      </div>

      {(lastCheck ?? check.isPending) && (
        <p className={styles.check} aria-live="polite">
          {check.isPending ? "Vérification en cours…" : lastCheck}
        </p>
      )}

      {editing && (
        <form className={styles.form} onSubmit={submit}>
          <label htmlFor={inputId} className="visually-hidden">
            Nouvelle valeur pour {secret.label}
          </label>
          <input
            id={inputId}
            className={styles.input}
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="Colle la clé ici"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
            }}
          />
          <Button type="submit" variant="primary" size="sm" busy={save.isPending}>
            Enregistrer
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setEditing(false);
              setValue("");
            }}
          >
            Annuler
          </Button>
        </form>
      )}
      {error && (
        <p className={styles.ko} role="alert">
          {describeError(error)}
        </p>
      )}
    </li>
  );
}
