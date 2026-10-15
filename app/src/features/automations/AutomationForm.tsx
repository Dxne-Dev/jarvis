import { useId, useState, type SyntheticEvent } from "react";

import { Button } from "../../components/Button";
import { describeError } from "../../lib/engine/client";
import { useAutomationEvents, useSaveAutomation } from "../../lib/engine/queries";
import type {
  Automation,
  AutomationAction,
  AutomationDraft,
  AutomationTrigger,
  Schedule,
} from "../../lib/engine/types";
import styles from "./Automations.module.css";

const DAYS = ["L", "M", "M", "J", "V", "S", "D"];
const DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];

type Frequency = "chaque_jour" | "certains_jours" | "une_fois" | "intervalle" | "chaque_mois";

interface FormState {
  name: string;
  mode: "horaire" | "evenement";
  frequency: Frequency;
  time: string;
  days: number[];
  at: string;
  minutes: number;
  dayOfMonth: number;
  event: string;
  actionType: AutomationAction["type"];
  text: string;
}

function initial(automation?: Automation): FormState {
  const state: FormState = {
    name: automation?.name ?? "",
    mode: automation?.trigger.type ?? "horaire",
    frequency: "chaque_jour",
    time: "08:00",
    days: [0, 1, 2, 3, 4],
    at: "",
    minutes: 60,
    dayOfMonth: 1,
    event: "plan.finished",
    actionType: automation?.action.type ?? "rappel",
    text: automation?.action.texte ?? "",
  };
  const trigger = automation?.trigger;
  if (trigger?.type === "evenement") state.event = trigger.evenement;
  if (trigger?.type === "horaire") {
    const when = trigger.quand;
    if (when.type === "chaque_jour") {
      state.time = when.heure;
      state.days = when.jours;
      state.frequency = when.jours.length === 7 ? "chaque_jour" : "certains_jours";
    } else if (when.type === "une_fois") {
      state.frequency = "une_fois";
      state.at = when.le;
    } else if (when.type === "intervalle") {
      state.frequency = "intervalle";
      state.minutes = when.minutes;
    } else {
      state.frequency = "chaque_mois";
      state.dayOfMonth = when.jour;
      state.time = when.heure;
    }
  }
  return state;
}

function schedule(state: FormState): Schedule {
  switch (state.frequency) {
    case "chaque_jour":
      return { type: "chaque_jour", heure: state.time, jours: [0, 1, 2, 3, 4, 5, 6] };
    case "certains_jours":
      return {
        type: "chaque_jour",
        heure: state.time,
        jours: [...state.days].sort((a, b) => a - b),
      };
    case "une_fois":
      return { type: "une_fois", le: state.at };
    case "intervalle":
      return { type: "intervalle", minutes: state.minutes };
    case "chaque_mois":
      return { type: "chaque_mois", jour: state.dayOfMonth, heure: state.time };
  }
}

function draft(state: FormState): AutomationDraft {
  const trigger: AutomationTrigger =
    state.mode === "horaire"
      ? { type: "horaire", quand: schedule(state) }
      : { type: "evenement", evenement: state.event };
  return {
    name: state.name.trim(),
    trigger,
    action: { type: state.actionType, texte: state.text.trim() },
  };
}

/** Créer ou modifier une automatisation : quand, puis quoi. */
export function AutomationForm({
  automation,
  onDone,
}: {
  automation?: Automation;
  onDone: () => void;
}) {
  const [state, setState] = useState<FormState>(() => initial(automation));
  const save = useSaveAutomation();
  const events = useAutomationEvents();
  const id = useId();
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setState((current) => ({ ...current, [key]: value }));
  };
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate(automation ? { id: automation.id, draft: draft(state) } : { draft: draft(state) }, {
      onSuccess: onDone,
    });
  };
  const needsTime = ["chaque_jour", "certains_jours", "chaque_mois"].includes(state.frequency);
  const invalid =
    state.name.trim().length < 2 ||
    state.text.trim().length < (state.actionType === "consigne" ? 3 : 1) ||
    (state.mode === "horaire" && state.frequency === "une_fois" && !state.at) ||
    (state.mode === "horaire" && state.frequency === "certains_jours" && state.days.length === 0);

  return (
    <form
      className={styles.form}
      onSubmit={submit}
      aria-label={automation ? "Modifier l'automatisation" : "Nouvelle automatisation"}
    >
      <div className={styles.field}>
        <label htmlFor={`${id}-nom`}>Nom</label>
        <input
          id={`${id}-nom`}
          className={styles.input}
          value={state.name}
          maxLength={120}
          placeholder="ex. Briefing du matin"
          onChange={(e) => {
            set("name", e.target.value);
          }}
        />
      </div>

      <fieldset className={styles.fieldset}>
        <legend>Quand</legend>
        <div className={styles.segmented}>
          {(
            [
              ["horaire", "À une heure"],
              ["evenement", "Quand quelque chose arrive"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className={styles.option}>
              <input
                type="radio"
                name={`${id}-mode`}
                checked={state.mode === value}
                onChange={() => {
                  set("mode", value);
                }}
              />
              {label}
            </label>
          ))}
        </div>
        {state.mode === "horaire" ? (
          <div className={styles.row}>
            <div className={styles.field}>
              <label htmlFor={`${id}-frequence`}>Fréquence</label>
              <select
                id={`${id}-frequence`}
                className={styles.input}
                value={state.frequency}
                onChange={(e) => {
                  set("frequency", e.target.value as Frequency);
                }}
              >
                <option value="chaque_jour">Chaque jour</option>
                <option value="certains_jours">Certains jours</option>
                <option value="une_fois">Une seule fois</option>
                <option value="intervalle">À intervalle</option>
                <option value="chaque_mois">Chaque mois</option>
              </select>
            </div>
            {needsTime && (
              <div className={styles.field}>
                <label htmlFor={`${id}-heure`}>Heure</label>
                <input
                  id={`${id}-heure`}
                  type="time"
                  className={styles.input}
                  value={state.time}
                  onChange={(e) => {
                    set("time", e.target.value);
                  }}
                />
              </div>
            )}
            {state.frequency === "une_fois" && (
              <div className={styles.field}>
                <label htmlFor={`${id}-le`}>Date et heure</label>
                <input
                  id={`${id}-le`}
                  type="datetime-local"
                  className={styles.input}
                  value={state.at}
                  onChange={(e) => {
                    set("at", e.target.value);
                  }}
                />
              </div>
            )}
            {state.frequency === "intervalle" && (
              <div className={styles.field}>
                <label htmlFor={`${id}-minutes`}>Toutes les (minutes)</label>
                <input
                  id={`${id}-minutes`}
                  type="number"
                  min={5}
                  className={styles.input}
                  value={state.minutes}
                  onChange={(e) => {
                    set("minutes", Number(e.target.value));
                  }}
                />
              </div>
            )}
            {state.frequency === "chaque_mois" && (
              <div className={styles.field}>
                <label htmlFor={`${id}-jour`}>Jour du mois</label>
                <input
                  id={`${id}-jour`}
                  type="number"
                  min={1}
                  max={31}
                  className={styles.input}
                  value={state.dayOfMonth}
                  onChange={(e) => {
                    set("dayOfMonth", Number(e.target.value));
                  }}
                />
              </div>
            )}
            {state.frequency === "certains_jours" && (
              <div className={styles.days} role="group" aria-label="Jours de la semaine">
                {DAYS.map((letter, day) => (
                  <label key={DAY_NAMES[day]} className={styles.day} title={DAY_NAMES[day]}>
                    <input
                      type="checkbox"
                      checked={state.days.includes(day)}
                      onChange={(e) => {
                        set(
                          "days",
                          e.target.checked
                            ? [...state.days, day]
                            : state.days.filter((d) => d !== day),
                        );
                      }}
                    />
                    <span aria-hidden="true">{letter}</span>
                    <span className="visually-hidden">{DAY_NAMES[day]}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className={styles.field}>
            <label htmlFor={`${id}-evenement`}>Événement</label>
            <select
              id={`${id}-evenement`}
              className={styles.input}
              value={state.event}
              onChange={(e) => {
                set("event", e.target.value);
              }}
            >
              {(events.data ?? []).map((ev) => (
                <option key={ev.type} value={ev.type}>
                  {ev.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </fieldset>

      <fieldset className={styles.fieldset}>
        <legend>Quoi</legend>
        <div className={styles.segmented}>
          {(
            [
              ["rappel", "Un rappel"],
              ["consigne", "Une tâche pour Jarvis"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className={styles.option}>
              <input
                type="radio"
                name={`${id}-action`}
                checked={state.actionType === value}
                onChange={() => {
                  set("actionType", value);
                }}
              />
              {label}
            </label>
          ))}
        </div>
        <div className={styles.field}>
          <label htmlFor={`${id}-texte`}>
            {state.actionType === "rappel" ? "Message du rappel" : "Ce que Jarvis doit faire"}
          </label>
          <textarea
            id={`${id}-texte`}
            className={styles.textarea}
            rows={3}
            maxLength={2000}
            value={state.text}
            placeholder={
              state.actionType === "rappel"
                ? "ex. Boire un grand verre d'eau."
                : "ex. Résume les nouvelles de la tech du jour en cinq points."
            }
            onChange={(e) => {
              set("text", e.target.value);
            }}
          />
          {state.actionType === "consigne" && (
            <p className={styles.hint}>
              Jarvis lit et cherche seul. S&apos;il faut agir (écrire, cliquer…), il prépare un plan
              et attend ta validation.
            </p>
          )}
        </div>
      </fieldset>

      {save.isError && (
        <p className={styles.error} role="alert">
          {describeError(save.error)}
        </p>
      )}
      <div className={styles.formActions}>
        <Button onClick={onDone}>Annuler</Button>
        <Button type="submit" variant="primary" busy={save.isPending} disabled={invalid}>
          Enregistrer
        </Button>
      </div>
    </form>
  );
}
