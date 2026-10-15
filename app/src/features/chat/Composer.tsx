import { ArrowUp, Square } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import styles from "./Chat.module.css";

interface ComposerProps {
  busy: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

const MAX_ROWS_PX = 180;

export function Composer({ busy, disabled, onSend, onStop }: ComposerProps) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const hintId = useId();

  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, MAX_ROWS_PX)}px`;
  }, [text]);

  const submit = () => {
    if (!text.trim() || busy || disabled) return;
    onSend(text);
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className={styles.composer}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor={`${hintId}-field`} className="visually-hidden">
        Message pour Jarvis
      </label>
      <textarea
        id={`${hintId}-field`}
        ref={ref}
        className={styles.field}
        rows={1}
        placeholder={disabled ? "Le moteur est hors ligne…" : "Écris à Jarvis…"}
        value={text}
        disabled={disabled}
        aria-describedby={hintId}
        onChange={(event) => {
          setText(event.target.value);
        }}
        onKeyDown={onKeyDown}
      />
      <p id={hintId} className="visually-hidden">
        Entrée pour envoyer, Maj et Entrée pour aller à la ligne.
      </p>
      {busy ? (
        <button
          type="button"
          className={styles.send}
          onClick={onStop}
          aria-label="Arrêter la réponse"
        >
          <Square aria-hidden="true" />
        </button>
      ) : (
        <button
          type="submit"
          className={styles.send}
          disabled={disabled || !text.trim()}
          aria-label="Envoyer"
        >
          <ArrowUp aria-hidden="true" />
        </button>
      )}
    </form>
  );
}
