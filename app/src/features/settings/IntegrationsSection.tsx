import { Switch } from "radix-ui";
import { CalendarDays, GitPullRequest, MessageCircle, NotebookText, Sunrise } from "lucide-react";
import type { ComponentType, SVGProps } from "react";

import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorState, LoadingState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useGoogleAccount,
  useIntegrations,
  usePreferences,
  useReconnectIntegration,
  useStartBriefing,
  useTelegram,
  useUpdatePreferences,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { Integration } from "../../lib/engine/types";
import { openExternal } from "../../lib/links";
import styles from "./SettingsScreen.module.css";

const ICONS: Record<Integration["name"], ComponentType<SVGProps<SVGSVGElement>>> = {
  github: GitPullRequest,
  notion: NotebookText,
  agenda: CalendarDays,
};

function statusText(integration: Integration): string {
  if (integration.name === "agenda" && !integration.account_configured)
    return "Ajoute d'abord GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET (Fournisseurs et clés).";
  if (integration.name === "agenda" && !integration.account_connected)
    return "Pas encore connecté à ton compte Google.";
  if (!integration.configured) return "Clé absente (Fournisseurs et clés).";
  switch (integration.status) {
    case "prêt":
      return `Prêt · ${integration.tools} outils${integration.detail ? ` · ${integration.detail}` : ""}`;
    case "connexion":
      return "Connexion au serveur…";
    case "erreur":
      return `Indisponible : ${integration.error ?? "erreur inconnue"}`;
    default:
      return "Démarre à la première utilisation.";
  }
}

function tone(integration: Integration): "ok" | "down" | "idle" {
  if (integration.status === "prêt") return "ok";
  if (integration.status === "erreur") return "down";
  return "idle";
}

function IntegrationRow({ integration, online }: { integration: Integration; online: boolean }) {
  const reconnect = useReconnectIntegration();
  const google = useGoogleAccount();
  const Icon = ICONS[integration.name];
  const error = reconnect.error ?? google.error;
  const isAgenda = integration.name === "agenda";
  return (
    <li className={styles.secret}>
      <div className={styles.grantHead}>
        <Icon className={styles.secretIcon} aria-hidden="true" />
        <div className={styles.secretText}>
          <p className={styles.secretLabel}>{integration.label}</p>
          <p className={styles.secretHelp}>{integration.about}</p>
          <p className={styles.integrationStatus} data-tone={tone(integration)}>
            {statusText(integration)}
          </p>
        </div>
        <div className={styles.actions}>
          {isAgenda && integration.account_configured && !integration.account_connected && (
            <Button
              size="sm"
              variant="primary"
              disabled={!online}
              busy={google.isPending}
              onClick={() => {
                google.mutate("connect", {
                  onSuccess: (url) => {
                    if (url) void openExternal(url);
                  },
                });
              }}
            >
              Connecter
            </Button>
          )}
          {(integration.configured || integration.account_connected) && (
            <Button
              size="sm"
              disabled={!online}
              busy={reconnect.isPending}
              onClick={() => {
                reconnect.mutate(integration.name);
              }}
            >
              Reconnecter
            </Button>
          )}
          {isAgenda && integration.account_connected && (
            <ConfirmDialog
              trigger={
                <Button size="sm" variant="ghost" disabled={!online}>
                  Déconnecter
                </Button>
              }
              title="Déconnecter Google Agenda ?"
              description="Jarvis oublie son accès à ton agenda (le jeton est révoqué et retiré du trousseau). Tu pourras le reconnecter."
              confirmLabel="Déconnecter"
              cancelLabel="Garder"
              onConfirm={() => {
                google.mutate("disconnect");
              }}
            />
          )}
        </div>
      </div>
      {google.isSuccess && google.data && (
        <p className={styles.check} role="status">
          La page de Google s&apos;est ouverte dans ton navigateur : accepte, puis reviens ici.
        </p>
      )}
      {error && (
        <p className={styles.ko} role="alert">
          {describeError(error)}
        </p>
      )}
    </li>
  );
}

function TelegramRow() {
  const telegram = useTelegram();
  const status = telegram.data;
  let text = "Lecture de l'état…";
  if (telegram.isError) text = describeError(telegram.error);
  else if (status && !status.configured)
    text = "Ajoute TELEGRAM_BOT_TOKEN et ton identifiant (Fournisseurs et clés).";
  else if (status?.connected)
    text = `Connecté à @${status.bot ?? "?"} · ${status.handled} message${status.handled > 1 ? "s" : ""} traité${status.handled > 1 ? "s" : ""}${status.rejected ? ` · ${status.rejected} expéditeur${status.rejected > 1 ? "s" : ""} refusé${status.rejected > 1 ? "s" : ""}` : ""}`;
  else if (status)
    text = `En attente de connexion${status.last_error ? ` : ${status.last_error}` : ""}`;
  return (
    <li className={styles.secret}>
      <div className={styles.grantHead}>
        <MessageCircle className={styles.secretIcon} aria-hidden="true" />
        <div className={styles.secretText}>
          <p className={styles.secretLabel}>Telegram</p>
          <p className={styles.secretHelp}>
            Parler à Jarvis depuis ton téléphone. Seul ton identifiant est servi ; une action de
            niveau 3 ne se valide jamais depuis Telegram.
          </p>
          <p
            className={styles.integrationStatus}
            data-tone={status?.connected ? "ok" : status?.last_error ? "down" : "idle"}
          >
            {text}
          </p>
        </div>
      </div>
    </li>
  );
}

function BriefingRow({ online }: { online: boolean }) {
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const start = useStartBriefing();
  const enabled = preferences.data?.briefing_enabled ?? true;
  return (
    <li className={styles.secret}>
      <div className={styles.grantHead}>
        <Sunrise className={styles.secretIcon} aria-hidden="true" />
        <div className={styles.secretText}>
          <p className={styles.secretLabel}>Briefing du matin</p>
          <p className={styles.secretHelp}>
            À ta première session du jour : agenda, PR et issues qui t&apos;attendent, rappels, ce
            que tes automatisations ont fait cette nuit.
          </p>
        </div>
        <div className={styles.actions}>
          <Switch.Root
            className={styles.switch}
            checked={enabled}
            disabled={!online || update.isPending}
            aria-label="Briefing du matin"
            onCheckedChange={(value) => {
              update.mutate({ briefing_enabled: value });
            }}
          >
            <Switch.Thumb className={styles.switchThumb} />
          </Switch.Root>
          <Button
            size="sm"
            disabled={!online}
            busy={start.isPending}
            onClick={() => {
              start.mutate(true);
            }}
          >
            Écouter maintenant
          </Button>
        </div>
      </div>
      {start.isSuccess && (
        <p className={styles.check} role="status">
          Briefing en préparation : Jarvis le dit dans quelques secondes.
        </p>
      )}
    </li>
  );
}

export function IntegrationsSection() {
  const integrations = useIntegrations();
  const online = useEngineOnline();
  if (!online && !integrations.data)
    return <p className={styles.note}>Disponible dès que le moteur répondra.</p>;
  if (integrations.isPending) return <LoadingState label="Lecture des intégrations…" />;
  if (integrations.isError)
    return (
      <ErrorState
        message={describeError(integrations.error)}
        onRetry={() => {
          void integrations.refetch();
        }}
      />
    );
  return (
    <ul className={styles.secrets} aria-label="Intégrations">
      {integrations.data.map((integration) => (
        <IntegrationRow key={integration.name} integration={integration} online={online} />
      ))}
      <TelegramRow />
      <BriefingRow online={online} />
    </ul>
  );
}
