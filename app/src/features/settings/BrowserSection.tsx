import { Globe, LogIn } from "lucide-react";
import { useId, useState, type SyntheticEvent } from "react";

import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorState, LoadingState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useBrowser,
  useBrowserLogin,
  useImportCookies,
  useRevokeCookies,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import { PreferenceSwitch } from "./PreferenceControls";
import type { BrowserGrant, BrowserState } from "../../lib/engine/types";
import { formatRelative } from "../../lib/format";
import styles from "./SettingsScreen.module.css";

const SOURCE_LABEL: Record<string, string> = {
  connexion: "connexion dans sa fenêtre",
  chrome: "importés de Google Chrome",
  chromium: "importés de Chromium",
  brave: "importés de Brave",
};

function LoginBlock({ state, disabled }: { state: BrowserState; disabled: boolean }) {
  const [site, setSite] = useState("");
  const login = useBrowserLogin();
  const inputId = useId();
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!site.trim()) return;
    login.mutate({ action: "start", url: site.trim() });
  };
  return (
    <div className={styles.secret}>
      <div className={styles.secretText}>
        <p className={styles.secretLabel}>Te connecter à un site</p>
        <p className={styles.secretHelp}>
          Une fenêtre du navigateur de Jarvis s&apos;ouvre : tu t&apos;y connectes toi-même, puis tu
          la fermes. Jarvis garde la session de ce site seulement, jamais ton mot de passe.
        </p>
      </div>
      {state.login_domain ? (
        <div className={styles.blockForm} role="status">
          <p className={styles.note}>
            Fenêtre ouverte sur <strong>{state.login_domain}</strong>. Connecte-toi, puis ferme-la
            ou clique sur « Terminer ».
          </p>
          <Button
            variant="primary"
            size="sm"
            busy={login.isPending}
            onClick={() => {
              login.mutate({ action: "finish" });
            }}
          >
            Terminer
          </Button>
        </div>
      ) : (
        <form className={styles.blockForm} onSubmit={submit}>
          <label htmlFor={inputId} className="visually-hidden">
            Site où te connecter
          </label>
          <input
            id={inputId}
            className={styles.input}
            type="text"
            inputMode="url"
            spellCheck={false}
            placeholder="ex. github.com"
            value={site}
            disabled={disabled}
            onChange={(e) => {
              setSite(e.target.value);
            }}
          />
          <Button
            type="submit"
            size="sm"
            icon={<LogIn />}
            busy={login.isPending}
            disabled={disabled}
          >
            Ouvrir la fenêtre
          </Button>
        </form>
      )}
      {login.isError && (
        <p className={styles.ko} role="alert">
          {describeError(login.error)}
        </p>
      )}
    </div>
  );
}

function ImportBlock({ state, disabled }: { state: BrowserState; disabled: boolean }) {
  const [source, setSource] = useState(state.sources[0]?.id ?? "");
  const [domain, setDomain] = useState("");
  const [allowed, setAllowed] = useState(false);
  const importCookies = useImportCookies();
  const ids = { source: useId(), domain: useId(), consent: useId() };
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!allowed || !domain.trim() || !source) return;
    importCookies.mutate(
      { source, domain: domain.trim() },
      {
        onSuccess: () => {
          setDomain("");
          setAllowed(false);
        },
      },
    );
  };
  return (
    <div className={styles.secret}>
      <div className={styles.secretText}>
        <p className={styles.secretLabel}>Importer les cookies d&apos;un domaine</p>
        <p className={styles.secretHelp}>
          Seuls les cookies du domaine choisi sont lus dans ton navigateur. Ils restent chiffrés sur
          cette machine et ne sont jamais envoyés à un modèle.
        </p>
      </div>
      {state.sources.length === 0 ? (
        <p className={styles.note}>Aucun profil Chrome, Chromium ou Brave trouvé.</p>
      ) : (
        <form className={styles.importForm} onSubmit={submit}>
          <label htmlFor={ids.source} className={styles.fieldLabel}>
            Navigateur
          </label>
          <select
            id={ids.source}
            className={`${styles.input} ${styles.select}`}
            value={source}
            disabled={disabled}
            onChange={(e) => {
              setSource(e.target.value);
            }}
          >
            {state.sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <label htmlFor={ids.domain} className={styles.fieldLabel}>
            Domaine
          </label>
          <input
            id={ids.domain}
            className={styles.input}
            type="text"
            spellCheck={false}
            placeholder="ex. github.com"
            value={domain}
            disabled={disabled}
            onChange={(e) => {
              setDomain(e.target.value);
            }}
          />
          <label htmlFor={ids.consent} className={styles.consent}>
            <input
              id={ids.consent}
              type="checkbox"
              checked={allowed}
              disabled={disabled}
              onChange={(e) => {
                setAllowed(e.target.checked);
              }}
            />
            J&apos;autorise Jarvis à utiliser ma session sur ce domaine (chaque visite me sera
            soumise).
          </label>
          <Button
            type="submit"
            size="sm"
            variant="primary"
            busy={importCookies.isPending}
            disabled={disabled || !allowed || !domain.trim()}
          >
            Importer
          </Button>
        </form>
      )}
      {importCookies.isError && (
        <p className={styles.ko} role="alert">
          {describeError(importCookies.error)}
        </p>
      )}
      {importCookies.isSuccess && (
        <p className={styles.ok} role="status">
          {importCookies.data.count} cookie{importCookies.data.count > 1 ? "s" : ""} de{" "}
          {importCookies.data.domain} importé{importCookies.data.count > 1 ? "s" : ""}.
        </p>
      )}
    </div>
  );
}

function GrantRow({ grant, disabled }: { grant: BrowserGrant; disabled: boolean }) {
  const revoke = useRevokeCookies();
  return (
    <li className={styles.secret}>
      <div className={styles.grantHead}>
        <Globe className={styles.secretIcon} aria-hidden="true" />
        <div className={styles.secretText}>
          <p className={styles.secretLabel}>{grant.domain}</p>
          <p className={styles.secretHelp}>
            {SOURCE_LABEL[grant.source] ?? grant.source} · {grant.count} cookie
            {grant.count > 1 ? "s" : ""} · {formatRelative(grant.imported_at)}
          </p>
        </div>
        <ConfirmDialog
          trigger={
            <Button size="sm" variant="ghost" disabled={disabled} busy={revoke.isPending}>
              Révoquer
            </Button>
          }
          title={`Révoquer l'accès à ${grant.domain} ?`}
          description="Jarvis efface ses cookies pour ce domaine et n'y utilisera plus ta session. Tu pourras le reconnecter plus tard."
          confirmLabel="Révoquer"
          cancelLabel="Garder"
          onConfirm={() => {
            revoke.mutate(grant.domain);
          }}
        />
      </div>
      {revoke.isError && (
        <p className={styles.ko} role="alert">
          {describeError(revoke.error)}
        </p>
      )}
    </li>
  );
}

export function BrowserSection() {
  const browser = useBrowser();
  const online = useEngineOnline();
  if (!online && !browser.data)
    return <p className={styles.note}>Disponible dès que le moteur répondra.</p>;
  if (browser.isPending) return <LoadingState label="Lecture des autorisations…" />;
  if (browser.isError)
    return (
      <ErrorState
        message={describeError(browser.error)}
        onRetry={() => {
          void browser.refetch();
        }}
      />
    );
  const state = browser.data;
  const disabled = !online;
  return (
    <>
      <p className={styles.groupDescription}>
        Jarvis a son propre navigateur. Il lit les pages sans tes cookies. Sur un domaine que tu
        autorises ici, il utilise ta session : chaque visite devient une action (niveau 2) que tu
        valides.
      </p>
      <PreferenceSwitch
        name="browser_visible"
        label="Montrer le navigateur de Jarvis"
        hint="Chromium s'ouvre en fenêtre : tu vois chaque page, chaque clic, chaque champ rempli. Rien ne change aux validations."
      />
      <div className={styles.group}>
        <div>
          <h3 className={styles.groupTitle}>Autoriser un domaine</h3>
          <p className={styles.groupDescription}>Deux façons, toujours à ton initiative.</p>
        </div>
        <div className={styles.secrets}>
          <LoginBlock state={state} disabled={disabled} />
          <ImportBlock key={state.sources.length} state={state} disabled={disabled} />
        </div>
      </div>
      <div className={styles.group}>
        <div>
          <h3 className={styles.groupTitle}>Domaines autorisés</h3>
          <p className={styles.groupDescription}>Révocables à tout moment.</p>
        </div>
        {state.grants.length === 0 ? (
          <p className={styles.note}>Aucun : Jarvis navigue sans aucune de tes sessions.</p>
        ) : (
          <ul className={styles.secrets} aria-label="Domaines autorisés">
            {state.grants.map((grant) => (
              <GrantRow key={grant.domain} grant={grant} disabled={disabled} />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
