import { MessageSquare, Mic, Pencil, Search, Trash2 } from "lucide-react";
import { useDeferredValue, useId, useState, type SyntheticEvent } from "react";
import { useNavigate } from "react-router";

import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useConversations,
  useDeleteConversation,
  useRenameConversation,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { Conversation } from "../../lib/engine/types";
import { formatRelative } from "../../lib/format";
import styles from "./HistoryScreen.module.css";

function ConversationRow({ conversation }: { conversation: Conversation }) {
  const navigate = useNavigate();
  const rename = useRenameConversation();
  const remove = useDeleteConversation();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conversation.title);
  const fieldId = useId();

  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!title.trim()) return;
    rename.mutate(
      { id: conversation.id, title },
      {
        onSuccess: () => {
          setEditing(false);
        },
      },
    );
  };

  const Icon = conversation.channel === "voice" ? Mic : MessageSquare;
  return (
    <li className={styles.row}>
      <Icon className={styles.icon} aria-hidden="true" />
      {editing ? (
        <form className={styles.renameForm} onSubmit={submit}>
          <label htmlFor={fieldId} className="visually-hidden">
            Nouveau titre
          </label>
          <input
            id={fieldId}
            className={styles.input}
            value={title}
            maxLength={200}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
          <Button type="submit" size="sm" variant="primary" busy={rename.isPending}>
            Renommer
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setEditing(false);
              setTitle(conversation.title);
            }}
          >
            Annuler
          </Button>
        </form>
      ) : (
        <button
          type="button"
          className={styles.open}
          onClick={() => {
            void navigate(`/?c=${encodeURIComponent(conversation.id)}`);
          }}
        >
          <span className={styles.title}>{conversation.title}</span>
          <span className={styles.preview}>{conversation.preview || "Conversation vide"}</span>
        </button>
      )}
      <span className={styles.meta}>
        {formatRelative(conversation.updated_at)} · {conversation.message_count} message
        {conversation.message_count > 1 ? "s" : ""}
      </span>
      {!editing && (
        <div className={styles.actions}>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Renommer « ${conversation.title} »`}
            icon={<Pencil />}
            onClick={() => {
              setEditing(true);
            }}
          />
          <ConfirmDialog
            trigger={
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Supprimer « ${conversation.title} »`}
                icon={<Trash2 />}
              />
            }
            title={`Supprimer « ${conversation.title} » ?`}
            description="La conversation et ses messages seront effacés. Les souvenirs que Jarvis en a tirés restent dans la Mémoire."
            confirmLabel="Supprimer"
            onConfirm={() => {
              remove.mutate(conversation.id);
            }}
          />
        </div>
      )}
      {(rename.error ?? remove.error) && (
        <p className={styles.error} role="alert">
          {describeError(rename.error ?? remove.error)}
        </p>
      )}
    </li>
  );
}

export function HistoryScreen() {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const conversations = useConversations(deferred);
  const online = useEngineOnline();
  const searchId = useId();

  let content;
  if (!online && !conversations.data) content = <OfflineState what="L'historique" />;
  else if (conversations.isPending) content = <LoadingState label="Lecture de l'historique…" />;
  else if (conversations.isError)
    content = (
      <ErrorState
        message={describeError(conversations.error)}
        onRetry={() => {
          void conversations.refetch();
        }}
      />
    );
  else if (conversations.data.length === 0)
    content = deferred ? (
      <EmptyState title="Aucun résultat">
        Aucune conversation ne contient « {deferred} ».
      </EmptyState>
    ) : (
      <EmptyState title="Pas encore de conversation">
        Écris ou parle à Jarvis depuis l'Accueil : chaque échange arrive ici.
      </EmptyState>
    );
  else
    content = (
      <ul className={styles.list} aria-label="Conversations">
        {conversations.data.map((c) => (
          <ConversationRow key={c.id} conversation={c} />
        ))}
      </ul>
    );

  return (
    <div className={styles.page}>
      <PageHeader
        title="Historique"
        description="Toutes tes conversations, texte et voix. Recherche dans les messages."
      />
      <div className={styles.search}>
        <Search aria-hidden="true" />
        <label htmlFor={searchId} className="visually-hidden">
          Rechercher dans les conversations
        </label>
        <input
          id={searchId}
          type="search"
          className={styles.searchInput}
          placeholder="Rechercher un mot…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
          }}
        />
      </div>
      {content}
    </div>
  );
}
