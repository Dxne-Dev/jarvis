import { AlertCircle, BrainCircuit, ChevronDown } from "lucide-react";
import { memo, useId, useState, type ComponentProps } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatDuration } from "../../lib/format";
import { openExternal } from "../../lib/links";
import styles from "./Chat.module.css";
import type { ChatItem } from "./useChat";

const KIND_LABEL: Record<string, string> = {
  profil: "profil",
  fait: "fait",
  preference: "préférence",
  souvenir: "échange passé",
};

function ExternalLink({ href, children }: ComponentProps<"a">) {
  return (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        if (href) void openExternal(href);
      }}
      rel="noreferrer"
    >
      {children}
    </a>
  );
}

function formatCost(cost: number | null): string | null {
  if (cost === null) return null;
  if (cost === 0) return "gratuit";
  if (cost < 0.001) return "< 0,001 $";
  return `${cost.toFixed(3).replace(".", ",")} $`;
}

function ContextDisclosure({ item }: { item: ChatItem }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const used = (item.context ?? []).filter((c) => c.kept);
  if (used.length === 0) return null;
  return (
    <div className={styles.context}>
      <button
        type="button"
        className={styles.contextToggle}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          setOpen((v) => !v);
        }}
      >
        <BrainCircuit aria-hidden="true" />
        {used.length === 1 ? "1 souvenir utilisé" : `${used.length} souvenirs utilisés`}
        <ChevronDown className={styles.chevron} data-open={open} aria-hidden="true" />
      </button>
      {open && (
        <ul id={panelId} className={styles.contextList}>
          {used.map((c) => (
            <li key={`${c.kind}-${c.preview}`}>
              <span className={styles.contextKind}>{KIND_LABEL[c.kind] ?? c.kind}</span>
              {c.preview}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export const ChatMessage = memo(function ChatMessage({ item }: { item: ChatItem }) {
  if (item.role === "user") {
    return (
      <li className={styles.user}>
        <p className={styles.userBubble}>{item.content}</p>
      </li>
    );
  }
  const streaming = item.status === "streaming";
  const meta = item.meta;
  const details = [
    meta?.model,
    meta?.latencyMs ? formatDuration(meta.latencyMs) : null,
    formatCost(meta?.costUsd ?? null),
  ].filter(Boolean);
  return (
    <li className={styles.assistant} aria-busy={streaming}>
      <span className="visually-hidden">Jarvis :</span>
      {item.content ? (
        <div className={styles.markdown}>
          <Markdown remarkPlugins={[remarkGfm]} components={{ a: ExternalLink }}>
            {item.content}
          </Markdown>
        </div>
      ) : (
        streaming && (
          <p className={styles.waiting} role="status">
            Jarvis réfléchit…
          </p>
        )
      )}
      {item.status === "interrupted" && <p className={styles.note}>Réponse interrompue.</p>}
      {item.status === "error" && (
        <p className={styles.error} role="alert">
          <AlertCircle aria-hidden="true" />
          {item.error ?? "La réponse n'a pas pu aboutir."}
        </p>
      )}
      {meta?.fallbackFrom && (
        <p className={styles.note}>
          {meta.fallbackFrom.split("/")[0]} ne répondait pas : réponse de {meta.provider}.
        </p>
      )}
      <ContextDisclosure item={item} />
      {details.length > 0 && <p className={styles.meta}>{details.join(" · ")}</p>}
    </li>
  );
});
