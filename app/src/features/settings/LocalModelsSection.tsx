import { Check, FolderOpen, RotateCw, Upload, X } from "lucide-react";
import { useRef, useState, type ChangeEvent } from "react";

import { Button } from "../../components/Button";
import { ExternalLink } from "../../components/RichText";
import { ErrorState, LoadingState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useImportModelFile,
  useLocalModels,
  useOpenModelsFolder,
  useRetryLocalModels,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { LocalModel } from "../../lib/engine/types";
import styles from "./SettingsScreen.module.css";

function megabytes(bytes: number): string {
  const value = bytes / 1_000_000;
  return `${value < 10 ? value.toFixed(1).replace(".", ",") : Math.round(value)} Mo`;
}

/** Ce qui reste à recevoir pour ce modèle, en tenant compte des téléchargements entamés. */
function remaining(model: LocalModel): { left: number; received: number } {
  let left = 0;
  let received = 0;
  for (const file of model.files) {
    if (file.present) continue;
    received += file.partial;
    left += Math.max((file.size ?? 0) - file.partial, 0);
  }
  return { left, received };
}

function ModelRow({ model }: { model: LocalModel }) {
  const { left, received } = remaining(model);
  const detail = model.ready
    ? "Prêt"
    : [
        model.state,
        left > 0 && `${megabytes(left)} à télécharger`,
        received > 0 && `${megabytes(received)} déjà reçus`,
      ]
        .filter(Boolean)
        .join(" · ");
  return (
    <li className={styles.secret}>
      <div className={styles.secretText}>
        <p className={styles.secretLabel}>{model.label}</p>
        <p className={model.ready ? styles.ok : styles.secretHelp}>
          {model.ready && <Check aria-hidden="true" />}
          {detail}
        </p>
      </div>
    </li>
  );
}

interface ImportResult {
  name: string;
  message: string;
  ok: boolean;
}

function ManualDownload({ models }: { models: LocalModel[] }) {
  return (
    <details className={styles.manual}>
      <summary>Télécharger à la main (connexion faible)</summary>
      <p className={styles.note}>
        Ouvre chaque lien dans ton navigateur : il sait reprendre un téléchargement coupé. Puis
        clique sur « Importer des fichiers… » et choisis-les tous. Jarvis les reconnaît à leur
        empreinte et les range au bon endroit, même s&apos;ils ont été renommés.
      </p>
      {models.map((model) => (
        <div key={model.key} className={styles.manualModel}>
          <p className={styles.secretLabel}>{model.label}</p>
          <p className={styles.secretHelp}>
            Dossier : <code className={styles.code}>{model.folder}</code>
          </p>
          <ul className={styles.manualFiles}>
            {model.files
              .filter((file) => !file.present)
              .map((file) => (
                <li key={file.name}>
                  <ExternalLink href={file.url}>{file.name}</ExternalLink>
                  {file.size !== null && (
                    <span className={styles.meta}> · {megabytes(file.size)}</span>
                  )}
                </li>
              ))}
          </ul>
        </div>
      ))}
    </details>
  );
}

export function LocalModelsSection() {
  const models = useLocalModels();
  const online = useEngineOnline();
  const retry = useRetryLocalModels();
  const importFile = useImportModelFile();
  const openFolder = useOpenModelsFolder();
  const input = useRef<HTMLInputElement>(null);
  const [results, setResults] = useState<ImportResult[]>([]);

  if (!online && !models.data)
    return <p className={styles.note}>Disponible dès que le moteur répondra.</p>;
  if (models.isPending) return <LoadingState label="Lecture des modèles…" />;
  if (models.isError)
    return (
      <ErrorState
        message={describeError(models.error)}
        onRetry={() => {
          void models.refetch();
        }}
      />
    );

  const missing = models.data.filter((m) => !m.ready);

  const onFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    const done: ImportResult[] = [];
    for (const file of files) {
      try {
        const imported = await importFile.mutateAsync(file);
        done.push({ name: file.name, ok: true, message: `rangé dans ${imported.label}` });
      } catch (error) {
        done.push({ name: file.name, ok: false, message: describeError(error) });
      }
      setResults([...done]);
    }
  };

  return (
    <>
      <p className={styles.groupDescription}>
        Jarvis télécharge seul ces modèles pour la voix et la mémoire. Un téléchargement coupé
        reprend là où il s&apos;était arrêté.
      </p>
      <ul className={styles.secrets}>
        {models.data.map((model) => (
          <ModelRow key={model.key} model={model} />
        ))}
      </ul>
      {missing.length > 0 && (
        <>
          <div className={styles.actions}>
            <Button
              size="sm"
              icon={<RotateCw />}
              busy={retry.isPending}
              disabled={!online}
              onClick={() => {
                retry.mutate();
              }}
            >
              Réessayer
            </Button>
            <Button
              size="sm"
              icon={<Upload />}
              busy={importFile.isPending}
              disabled={!online}
              onClick={() => input.current?.click()}
            >
              Importer des fichiers…
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<FolderOpen />}
              disabled={!online}
              onClick={() => {
                openFolder.mutate();
              }}
            >
              Ouvrir le dossier
            </Button>
            <input
              ref={input}
              type="file"
              multiple
              hidden
              aria-label="Fichiers de modèles à importer"
              onChange={(event) => {
                void onFiles(event);
              }}
            />
          </div>
          <ManualDownload models={missing} />
        </>
      )}
      {retry.isError && (
        <p className={styles.ko} role="alert">
          {describeError(retry.error)}
        </p>
      )}
      {openFolder.isError && (
        <p className={styles.ko} role="alert">
          {describeError(openFolder.error)}
        </p>
      )}
      {results.length > 0 && (
        <ul className={styles.manualFiles} role="status">
          {results.map((result, index) => (
            <li key={`${result.name}-${index}`} className={result.ok ? styles.ok : styles.ko}>
              {result.ok ? <Check aria-hidden="true" /> : <X aria-hidden="true" />}
              {result.name} : {result.message}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
