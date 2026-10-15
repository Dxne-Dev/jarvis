import { Plus } from "lucide-react";
import { useId, useMemo, useState, type SyntheticEvent } from "react";

import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useAddEntity,
  useAddRelation,
  useDeleteEntity,
  useDeleteRelation,
  useMemoryGraph,
  useUpdateEntity,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { GraphEntity, GraphKind, GraphRelation } from "../../lib/engine/types";
import { formatRelative } from "../../lib/format";
import { layoutGraph } from "./graphLayout";
import styles from "./MemoryScreen.module.css";

const WIDTH = 760;
const HEIGHT = 480;

const KIND_LABEL: Record<GraphKind, string> = {
  moi: "Toi",
  personne: "Personne",
  projet: "Projet",
  evenement: "Événement",
  lieu: "Lieu",
  organisation: "Organisation",
  sujet: "Sujet",
};
const ADDABLE = (Object.keys(KIND_LABEL) as GraphKind[]).filter((k) => k !== "moi");

function nodeRadius(entity: GraphEntity): number {
  return entity.kind === "moi" ? 18 : Math.min(8 + entity.mentions * 2, 16);
}

function EntityDetails({
  entity,
  entities,
  relations,
  online,
  onDeleted,
}: {
  entity: GraphEntity;
  entities: GraphEntity[];
  relations: GraphRelation[];
  online: boolean;
  onDeleted: () => void;
}) {
  const update = useUpdateEntity();
  const remove = useDeleteEntity();
  const unlink = useDeleteRelation();
  const link = useAddRelation();
  const [description, setDescription] = useState(entity.description ?? "");
  const [target, setTarget] = useState("");
  const [label, setLabel] = useState("");
  const ids = { description: useId(), target: useId(), label: useId() };
  const names = new Map(entities.map((e) => [e.id, e.name]));
  const mine = relations.filter((r) => r.source_id === entity.id || r.target_id === entity.id);
  const error = update.error ?? remove.error ?? unlink.error ?? link.error;
  const saveDescription = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    update.mutate({ id: entity.id, description });
  };
  const addLink = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!target || label.trim().length < 2) return;
    link.mutate(
      { source_id: entity.id, label: label.trim(), target_id: Number(target) },
      {
        onSuccess: () => {
          setLabel("");
        },
      },
    );
  };
  return (
    <section className={styles.details} aria-labelledby={`entite-${entity.id}`}>
      <h3 id={`entite-${entity.id}`} className={styles.detailsTitle}>
        {entity.name}
      </h3>
      <p className={styles.meta}>
        {KIND_LABEL[entity.kind]} · cité {entity.mentions} fois · vu{" "}
        {formatRelative(entity.last_seen_at)}
      </p>
      <form className={styles.inlineForm} onSubmit={saveDescription}>
        <label htmlFor={ids.description} className={styles.fieldLabel}>
          Description
        </label>
        <input
          id={ids.description}
          className={styles.input}
          value={description}
          maxLength={300}
          onChange={(event) => {
            setDescription(event.target.value);
          }}
        />
        <Button type="submit" size="sm" disabled={!online} busy={update.isPending}>
          Enregistrer
        </Button>
      </form>
      {mine.length > 0 ? (
        <ul className={styles.relations} aria-label={`Liens de ${entity.name}`}>
          {mine.map((r) => (
            <li key={r.id} className={styles.relation}>
              <span>
                {names.get(r.source_id)} <em>{r.label}</em> {names.get(r.target_id)}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={!online}
                aria-label={`Retirer le lien «\u00a0${names.get(r.source_id)} ${r.label} ${names.get(r.target_id)}\u00a0»`}
                onClick={() => {
                  unlink.mutate(r.id);
                }}
              >
                Retirer
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.meta}>Aucun lien pour l&apos;instant.</p>
      )}
      <form className={styles.inlineForm} onSubmit={addLink}>
        <label htmlFor={ids.label} className={styles.fieldLabel}>
          Nouveau lien
        </label>
        <input
          id={ids.label}
          className={styles.input}
          placeholder="ex. travaille sur"
          value={label}
          maxLength={80}
          onChange={(event) => {
            setLabel(event.target.value);
          }}
        />
        <label htmlFor={ids.target} className="visually-hidden">
          Relier à
        </label>
        <select
          id={ids.target}
          className={styles.input}
          value={target}
          onChange={(event) => {
            setTarget(event.target.value);
          }}
        >
          <option value="">Relier à…</option>
          {entities
            .filter((e) => e.id !== entity.id)
            .map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
        </select>
        <Button
          type="submit"
          size="sm"
          disabled={!online || !target || label.trim().length < 2}
          busy={link.isPending}
        >
          Relier
        </Button>
      </form>
      {error && (
        <p className={styles.error} role="alert">
          {describeError(error)}
        </p>
      )}
      {entity.kind !== "moi" && (
        <ConfirmDialog
          trigger={
            <Button size="sm" variant="ghost" disabled={!online}>
              Oublier {entity.name}
            </Button>
          }
          title={`Oublier «\u00a0${entity.name}\u00a0» ?`}
          description="Jarvis efface cette entité et tous ses liens. Les souvenirs en phrases restent dans la liste."
          confirmLabel="Oublier"
          cancelLabel="Garder"
          onConfirm={() => {
            remove.mutate(entity.id, { onSuccess: onDeleted });
          }}
        />
      )}
    </section>
  );
}

function AddEntity({ online }: { online: boolean }) {
  const add = useAddEntity();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<GraphKind>("personne");
  const [description, setDescription] = useState("");
  const ids = { name: useId(), kind: useId(), description: useId() };
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) return;
    add.mutate(
      { name: name.trim(), kind, description: description.trim() },
      {
        onSuccess: () => {
          setName("");
          setDescription("");
        },
      },
    );
  };
  return (
    <form className={styles.addEntity} onSubmit={submit} aria-label="Ajouter une entité">
      <label htmlFor={ids.name} className={styles.fieldLabel}>
        Ajouter quelqu&apos;un ou quelque chose
      </label>
      <input
        id={ids.name}
        className={styles.input}
        placeholder="Nom"
        value={name}
        maxLength={120}
        onChange={(event) => {
          setName(event.target.value);
        }}
      />
      <label htmlFor={ids.kind} className="visually-hidden">
        Type
      </label>
      <select
        id={ids.kind}
        className={styles.input}
        value={kind}
        onChange={(event) => {
          setKind(event.target.value as GraphKind);
        }}
      >
        {ADDABLE.map((k) => (
          <option key={k} value={k}>
            {KIND_LABEL[k]}
          </option>
        ))}
      </select>
      <label htmlFor={ids.description} className="visually-hidden">
        Description
      </label>
      <input
        id={ids.description}
        className={styles.input}
        placeholder="Description (facultatif)"
        value={description}
        maxLength={300}
        onChange={(event) => {
          setDescription(event.target.value);
        }}
      />
      {add.isError && (
        <p className={styles.error} role="alert">
          {describeError(add.error)}
        </p>
      )}
      <Button type="submit" size="sm" icon={<Plus />} disabled={!online || !name.trim()}>
        Ajouter
      </Button>
    </form>
  );
}

export function MemoryGraphView() {
  const graph = useMemoryGraph();
  const online = useEngineOnline();
  const [selected, setSelected] = useState<number | null>(null);
  const data = graph.data;
  const positions = useMemo(
    () =>
      data
        ? layoutGraph(
            data.entities.map((e) => ({ id: e.id, fixed: e.kind === "moi" })),
            data.relations,
            WIDTH,
            HEIGHT,
          )
        : new Map<number, { x: number; y: number }>(),
    [data],
  );

  if (!online && !data) return <OfflineState what="Le graphe" />;
  if (graph.isPending) return <LoadingState label="Lecture du graphe…" />;
  if (graph.isError)
    return (
      <ErrorState
        message={describeError(graph.error)}
        onRetry={() => {
          void graph.refetch();
        }}
      />
    );
  const { entities, relations } = graph.data;
  const current = entities.find((e) => e.id === selected) ?? null;
  const degree = (id: number) =>
    relations.filter((r) => r.source_id === id || r.target_id === id).length;

  return (
    <div className={styles.graphLayout}>
      <div className={styles.graphCanvas}>
        {entities.length === 0 ? (
          <EmptyState title="Le graphe est vide">
            Parle à Jarvis de tes projets, de tes proches et des événements à venir : il les relie
            ici. Tu peux aussi en ajouter.
          </EmptyState>
        ) : (
          // Dessin pour la souris ; le même choix se fait au clavier dans la liste à côté.
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className={styles.graphSvg} aria-hidden="true">
            {relations.map((r) => {
              const a = positions.get(r.source_id);
              const b = positions.get(r.target_id);
              if (!a || !b) return null;
              const active = selected === r.source_id || selected === r.target_id;
              return (
                <g key={r.id} className={styles.edge} data-active={active}>
                  <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
                  <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} textAnchor="middle">
                    {r.label}
                  </text>
                </g>
              );
            })}
            {entities.map((e) => {
              const p = positions.get(e.id);
              if (!p) return null;
              const radius = nodeRadius(e);
              return (
                <g
                  key={e.id}
                  className={styles.node}
                  data-kind={e.kind}
                  data-selected={selected === e.id}
                  transform={`translate(${p.x} ${p.y})`}
                  onClick={() => {
                    setSelected(e.id);
                  }}
                >
                  <circle r={radius} />
                  <text y={radius + 14} textAnchor="middle">
                    {e.name}
                  </text>
                </g>
              );
            })}
          </svg>
        )}
        <ul className={styles.legend} aria-label="Légende">
          {(Object.keys(KIND_LABEL) as GraphKind[]).map((k) => (
            <li key={k} data-kind={k}>
              <span className={styles.legendDot} aria-hidden="true" />
              {KIND_LABEL[k]}
            </li>
          ))}
        </ul>
      </div>
      <div className={styles.graphSide}>
        {entities.length > 0 && (
          <ul className={styles.entityList} aria-label="Entités">
            {entities.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  className={styles.entityButton}
                  data-kind={e.kind}
                  aria-pressed={selected === e.id}
                  onClick={() => {
                    setSelected(e.id);
                  }}
                >
                  <span className={styles.legendDot} aria-hidden="true" />
                  {e.name}
                  <span className={styles.meta}>
                    {KIND_LABEL[e.kind]} · {degree(e.id)} lien{degree(e.id) > 1 ? "s" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {current && (
          <EntityDetails
            key={current.id}
            entity={current}
            entities={entities}
            relations={relations}
            online={online}
            onDeleted={() => {
              setSelected(null);
            }}
          />
        )}
        <AddEntity online={online} />
      </div>
    </div>
  );
}
