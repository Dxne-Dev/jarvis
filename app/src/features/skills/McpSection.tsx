import { Plug, Search } from "lucide-react";
import { useId, useState, type SyntheticEvent } from "react";

import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useInstallMcp,
  useMcpSearch,
  useMcpServers,
  useProbeMcp,
  useToggleMcp,
  useUninstallMcp,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { McpRegistryEntry, McpServerInfo, McpTool } from "../../lib/engine/types";
import { LEVEL_NAME } from "../actions/levels";
import styles from "./Skills.module.css";

const STATUS: Record<string, string> = {
  prêt: "Prêt",
  connexion: "Démarrage…",
  erreur: "En erreur",
  arrêté: "Démarre au premier usage",
  désactivé: "Désactivé",
};

/** « 6 outils : 5 en lecture, 1 en action » */
function toolSummary(tools: McpTool[]): string {
  const counts = new Map<string, number>();
  for (const tool of tools) {
    const name = LEVEL_NAME[tool.level].toLowerCase();
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const parts = [...counts].map(([name, n]) => `${n} en ${name}`);
  return `${tools.length} outil${tools.length > 1 ? "s" : ""}${parts.length ? ` : ${parts.join(", ")}` : ""}`;
}

function ServerCard({ server, online }: { server: McpServerInfo; online: boolean }) {
  const toggle = useToggleMcp();
  const remove = useUninstallMcp();
  const titleId = useId();
  const error = toggle.error ?? remove.error;
  return (
    <article
      className={styles.card}
      data-status={server.enabled ? "actif" : "desactive"}
      aria-labelledby={titleId}
    >
      <header className={styles.cardHead}>
        <Plug className={styles.cardIcon} aria-hidden="true" />
        <h3 id={titleId} className={styles.cardTitle}>
          {server.title} <span className={styles.version}>v{server.version}</span>
        </h3>
        <span
          className={styles.status}
          data-status={
            server.status === "erreur" ? "echec" : server.enabled ? "actif" : "desactive"
          }
        >
          {STATUS[server.status] ?? server.status}
        </span>
      </header>
      {server.description && <p className={styles.description}>{server.description}</p>}
      <p className={styles.permissions}>
        {server.label}, {server.where}.
      </p>
      <p className={styles.meta}>
        {toolSummary(server.tools)} · le modèle l&apos;appelle «&nbsp;{server.id}&nbsp;»
        {server.secret_names.length > 0 &&
          ` · clé au trousseau : ${server.secret_names.join(", ")}`}
      </p>
      {server.error && <p className={styles.error}>{server.error}</p>}
      {error && (
        <p className={styles.error} role="alert">
          {describeError(error)}
        </p>
      )}
      <div className={styles.cardActions}>
        <Button
          size="sm"
          disabled={!online}
          busy={toggle.isPending}
          onClick={() => {
            toggle.mutate({ id: server.id, enabled: !server.enabled });
          }}
        >
          {server.enabled ? "Désactiver" : "Réactiver"}
        </Button>
        <ConfirmDialog
          trigger={
            <Button size="sm" variant="ghost" disabled={!online}>
              Retirer
            </Button>
          }
          title={`Retirer «\u00a0${server.title}\u00a0» ?`}
          description="Jarvis perd ses outils ; sa clé est effacée du trousseau et son cache supprimé."
          confirmLabel="Retirer"
          cancelLabel="Garder"
          onConfirm={() => {
            remove.mutate(server.id);
          }}
        />
      </div>
    </article>
  );
}

function ResultCard({ entry, online }: { entry: McpRegistryEntry; online: boolean }) {
  const probe = useProbeMcp();
  const install = useInstallMcp();
  const titleId = useId();
  const fieldId = useId();
  const settings = entry.option?.settings ?? [];
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(settings.map((s) => [s.name, s.secret ? "" : (s.default ?? "")])),
  );
  const request = {
    name: entry.name,
    version: entry.version,
    variables: Object.fromEntries(
      settings
        .filter((s) => !s.secret && values[s.name])
        .map((s) => [s.name, values[s.name] ?? ""]),
    ),
    secrets: Object.fromEntries(
      settings.filter((s) => s.secret && values[s.name]).map((s) => [s.name, values[s.name] ?? ""]),
    ),
  };
  const missing = settings.some((s) => s.required && !values[s.name]);
  const result = probe.data;
  const error = probe.error ?? install.error;
  return (
    <article className={styles.card} aria-labelledby={titleId}>
      <header className={styles.cardHead}>
        <Plug className={styles.cardIcon} aria-hidden="true" />
        <h3 id={titleId} className={styles.cardTitle}>
          {entry.title} <span className={styles.version}>v{entry.version}</span>
        </h3>
        {entry.installed_id && (
          <span className={styles.status} data-status="actif">
            Installé
          </span>
        )}
      </header>
      <p className={styles.meta}>{entry.name}</p>
      {entry.description && <p className={styles.description}>{entry.description}</p>}
      {entry.option ? (
        <p className={styles.permissions}>
          {entry.option.label}, {entry.option.where}.
        </p>
      ) : (
        <p className={styles.error}>Impossible ici : {entry.why_not}.</p>
      )}
      {entry.option && !entry.installed_id && settings.length > 0 && (
        <div className={styles.settings}>
          {settings.map((s) => (
            <label key={s.name} className={styles.setting} htmlFor={`${fieldId}-${s.name}`}>
              <span>
                <code>{s.name}</code>
                {s.required ? " (obligatoire)" : ""}
                {s.secret ? " — clé, gardée au trousseau" : ""}
              </span>
              {s.description && <span className={styles.meta}>{s.description}</span>}
              <input
                id={`${fieldId}-${s.name}`}
                className={styles.input}
                type={s.secret ? "password" : "text"}
                autoComplete="off"
                spellCheck={false}
                value={values[s.name] ?? ""}
                onChange={(event) => {
                  setValues((v) => ({ ...v, [s.name]: event.target.value }));
                }}
              />
            </label>
          ))}
        </div>
      )}
      {result && (
        <div role="status">
          {result.ok ? (
            <>
              <p className={styles.tests} data-ok="true">
                Essai réussi en {result.seconds.toLocaleString("fr-FR")} s :{" "}
                {toolSummary(result.tools)}.
              </p>
              <ul className={styles.tools} aria-label={`Outils de ${entry.title}`}>
                {result.tools.map((t) => (
                  <li key={t.name}>
                    <code className={styles.toolName}>{t.name}</code> — {LEVEL_NAME[t.level]}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className={styles.tests} data-ok="false">
              L&apos;essai a échoué : {result.error}
            </p>
          )}
        </div>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {describeError(error)}
        </p>
      )}
      {entry.option && !entry.installed_id && (
        <div className={styles.cardActions}>
          <Button
            size="sm"
            disabled={!online || missing}
            busy={probe.isPending}
            onClick={() => {
              probe.mutate(request);
            }}
          >
            Essayer
          </Button>
          {result?.ok && (
            <ConfirmDialog
              trigger={
                <Button size="sm" variant="primary" disabled={!online} busy={install.isPending}>
                  Installer…
                </Button>
              }
              title={`Installer «\u00a0${entry.title}\u00a0» v${entry.version} ?`}
              description={`Jarvis pourra utiliser ses ${result.tools.length} outils : ${toolSummary(result.tools)}. Chaque action attendra ta validation. Il tourne ${entry.option.where}.`}
              confirmLabel="Installer"
              onConfirm={() => {
                install.mutate(request);
              }}
            />
          )}
        </div>
      )}
    </article>
  );
}

function RegistrySearch({ online }: { online: boolean }) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const results = useMcpSearch(query);
  const inputId = useId();
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    setQuery(draft.trim());
  };
  return (
    <div className={styles.registry}>
      <form className={styles.searchForm} onSubmit={submit} role="search">
        <label htmlFor={inputId} className={styles.subTitle}>
          Chercher dans le registre MCP officiel
        </label>
        <div className={styles.searchRow}>
          <input
            id={inputId}
            className={styles.input}
            value={draft}
            placeholder="ex. wikipedia, sqlite, github"
            onChange={(event) => {
              setDraft(event.target.value);
            }}
          />
          <Button type="submit" icon={<Search />} disabled={!online || draft.trim().length < 2}>
            Chercher
          </Button>
        </div>
      </form>
      {query.length >= 2 &&
        (results.isPending ? (
          <LoadingState label="Recherche dans le registre…" />
        ) : results.isError ? (
          <ErrorState
            message={describeError(results.error)}
            onRetry={() => {
              void results.refetch();
            }}
          />
        ) : results.data.length === 0 ? (
          <p className={styles.meta}>Aucun serveur ne correspond à «&nbsp;{query}&nbsp;».</p>
        ) : (
          <ul className={styles.list} aria-label="Résultats du registre">
            {results.data.map((entry) => (
              <li key={`${entry.name}@${entry.version}`}>
                <ResultCard entry={entry} online={online} />
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}

export function McpSection() {
  const servers = useMcpServers();
  const online = useEngineOnline();
  let installed;
  if (!online && !servers.data) installed = <OfflineState what="La liste des serveurs MCP" />;
  else if (servers.isPending) installed = <LoadingState label="Lecture des serveurs MCP…" />;
  else if (servers.isError)
    installed = (
      <ErrorState
        message={describeError(servers.error)}
        onRetry={() => {
          void servers.refetch();
        }}
      />
    );
  else if (servers.data.length === 0)
    installed = (
      <EmptyState title="Aucun serveur installé">
        Cherche un serveur ci-dessous, essaie-le, puis installe-le ; ou demande à Jarvis
        «&nbsp;installe le serveur MCP Wikipédia&nbsp;».
      </EmptyState>
    );
  else
    installed = (
      <ul className={styles.list} aria-label="Serveurs MCP installés">
        {servers.data.map((server) => (
          <li key={server.id}>
            <ServerCard server={server} online={online} />
          </li>
        ))}
      </ul>
    );
  return (
    <>
      {installed}
      <RegistrySearch online={online} />
    </>
  );
}
