import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "../../components/PageHeader";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import { useTrace, useTraces } from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { Span, TraceDetail, TraceSummary } from "../../lib/engine/types";
import { formatDateTime, formatDuration, formatRelative } from "../../lib/format";
import styles from "./JournalScreen.module.css";

const KIND_LABEL: Record<string, string> = {
  check: "vérification",
  chat: "conversation",
  voice: "voix",
  task: "tâche",
  http: "appel réseau",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "ok") return <CheckCircle2 className={styles.okIcon} aria-label="réussie" />;
  if (status === "error") return <XCircle className={styles.koIcon} aria-label="en échec" />;
  return <CircleDashed className={styles.runIcon} aria-label="en cours" />;
}

function TraceRow({
  trace,
  selected,
  onSelect,
}: {
  trace: TraceSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button type="button" className={styles.row} aria-pressed={selected} onClick={onSelect}>
        <StatusIcon status={trace.status} />
        <span className={styles.rowName}>{trace.name}</span>
        <span className={styles.tag}>{KIND_LABEL[trace.kind] ?? trace.kind}</span>
        <span className={styles.rowMeta}>{formatRelative(trace.started_at)}</span>
        <span className={styles.rowDuration}>{formatDuration(trace.duration_ms)}</span>
      </button>
    </li>
  );
}

function Waterfall({ trace }: { trace: TraceDetail }) {
  const start = new Date(trace.started_at).getTime();
  const total = Math.max(trace.duration_ms ?? 0, 1);
  const offset = (span: Span) => ((new Date(span.started_at).getTime() - start) / total) * 100;
  return (
    <ol className={styles.spans}>
      {trace.spans.map((span) => {
        const left = Math.min(Math.max(offset(span), 0), 100);
        const width = Math.max(((span.duration_ms ?? 0) / total) * 100, 1.5);
        return (
          <li key={span.id} className={styles.span}>
            <div className={styles.spanHead}>
              <StatusIcon status={span.status} />
              <span>{span.name}</span>
              <span className={styles.tag}>{KIND_LABEL[span.kind] ?? span.kind}</span>
              <span className={styles.rowDuration}>{formatDuration(span.duration_ms)}</span>
            </div>
            <div className={styles.track} aria-hidden="true">
              <span
                className={styles.bar}
                data-status={span.status}
                style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}
              />
            </div>
            {Object.keys(span.attributes).length > 0 && (
              <dl className={styles.attributes}>
                {Object.entries(span.attributes).map(([key, value]) => (
                  <div key={key} className={styles.attribute}>
                    <dt>{key}</dt>
                    <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            {span.error && <p className={styles.error}>{span.error}</p>}
          </li>
        );
      })}
    </ol>
  );
}

function TraceDetailPanel({ id }: { id: string | null }) {
  const trace = useTrace(id);
  if (id === null) {
    return (
      <EmptyState title="Choisis une trace">Ses étapes et leurs durées s'affichent ici.</EmptyState>
    );
  }
  if (trace.isPending) return <LoadingState label="Lecture de la trace…" />;
  if (trace.isError) return <ErrorState message={describeError(trace.error)} />;
  const t = trace.data;
  return (
    <article className={styles.detail} aria-labelledby="trace-titre">
      <header className={styles.detailHead}>
        <h2 id="trace-titre" className={styles.detailTitle}>
          {t.name}
        </h2>
        <p className={styles.detailMeta}>
          {formatDateTime(t.started_at)} · {formatDuration(t.duration_ms)} · corrélation{" "}
          <code>{t.correlation_id ?? "—"}</code>
        </p>
        {t.error && <p className={styles.error}>{t.error}</p>}
      </header>
      {t.spans.length === 0 ? (
        <EmptyState title="Aucune étape enregistrée" />
      ) : (
        <Waterfall trace={t} />
      )}
    </article>
  );
}

export function JournalScreen() {
  const traces = useTraces();
  const online = useEngineOnline();
  const [selected, setSelected] = useState<string | null>(null);

  let list;
  if (!online && !traces.data) list = <OfflineState what="Le journal" />;
  else if (traces.isPending) list = <LoadingState label="Lecture du journal…" />;
  else if (traces.isError)
    list = (
      <ErrorState
        message={describeError(traces.error)}
        onRetry={() => {
          void traces.refetch();
        }}
      />
    );
  else if (traces.data.length === 0)
    list = (
      <EmptyState title="Aucune trace pour l'instant">
        Chaque requête de Jarvis laisse une trace ici. Vérifie une clé dans Réglages pour en créer
        une.
      </EmptyState>
    );
  else
    list = (
      <ul className={styles.list} aria-label="Traces récentes">
        {traces.data.map((trace) => (
          <TraceRow
            key={trace.id}
            trace={trace}
            selected={trace.id === selected}
            onSelect={() => {
              setSelected(trace.id);
            }}
          />
        ))}
      </ul>
    );

  return (
    <div className={styles.page}>
      <PageHeader
        title="Journal et traces"
        description="Chaque requête suivie étape par étape : durée, modèle, coût."
      />
      <div className={styles.columns}>
        <section aria-label="Liste des traces">{list}</section>
        <section aria-label="Détail de la trace">
          <TraceDetailPanel id={selected} />
        </section>
      </div>
    </div>
  );
}
