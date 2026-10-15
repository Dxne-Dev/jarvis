import { Lightbulb } from "lucide-react";
import { useId } from "react";

import { Button } from "../../components/Button";
import { describeError } from "../../lib/engine/client";
import {
  useAcceptSuggestion,
  useDismissSuggestion,
  useSuggestions,
} from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import home from "./HomeScreen.module.css";

/** Les idées de Jarvis (demandes qui reviennent, projets laissés de côté), avec leur score. */
export function Suggestions({ onOpen }: { onOpen: (conversationId: string) => void }) {
  const suggestions = useSuggestions();
  const accept = useAcceptSuggestion();
  const dismiss = useDismissSuggestion();
  const online = useEngineOnline();
  const titleId = useId();
  const list = suggestions.data ?? [];
  if (list.length === 0) return null;
  const error = accept.error ?? dismiss.error;
  return (
    <section className={home.suggestions} aria-labelledby={titleId}>
      <h2 id={titleId} className={home.suggestionsTitle}>
        <Lightbulb aria-hidden="true" />
        Jarvis te suggère
      </h2>
      <ul className={home.suggestionList}>
        {list.slice(0, 3).map((s) => (
          <li key={s.id} className={home.suggestion}>
            <p className={home.suggestionText}>{s.title}</p>
            <p className={home.suggestionMeta}>
              {s.detail ? `${s.detail} · ` : ""}Confiance : {Math.round(s.confidence * 100)} %
            </p>
            <div className={home.suggestionActions}>
              {s.options.map((o) => (
                <Button
                  key={o.id}
                  size="sm"
                  disabled={!online || accept.isPending}
                  onClick={() => {
                    accept.mutate(
                      { id: s.id, option: o.id },
                      {
                        onSuccess: (done) => {
                          if (done.conversation_id) onOpen(done.conversation_id);
                        },
                      },
                    );
                  }}
                >
                  {o.label}
                </Button>
              ))}
              <Button
                size="sm"
                variant="ghost"
                disabled={!online}
                onClick={() => {
                  dismiss.mutate(s.id);
                }}
              >
                Écarter
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {error && (
        <p className={home.suggestionError} role="alert">
          {describeError(error)}
        </p>
      )}
    </section>
  );
}
