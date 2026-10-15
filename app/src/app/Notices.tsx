import { useEffect, useRef, useState } from "react";

import { useEngineStore } from "../lib/engine/store";
import { noticeFor } from "./notices";
import styles from "./Shell.module.css";

const VISIBLE_MS = 8000;

export function Notices() {
  const events = useEngineStore((s) => s.events);
  const [notice, setNotice] = useState<{ key: string; text: string } | null>(null);
  const seen = useRef<string | null>(null);

  useEffect(() => {
    const latest = events.find((e) => noticeFor(e) !== null);
    if (!latest) return;
    const key = `${String(latest.id)}-${latest.ts}`;
    if (seen.current === key) return;
    seen.current = key;
    setNotice({ key, text: noticeFor(latest) ?? "" });
    const timer = setTimeout(() => {
      setNotice(null);
    }, VISIBLE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [events]);

  return (
    <div className={styles.notices} role="status" aria-live="polite">
      {notice && (
        <p key={notice.key} className={styles.notice}>
          {notice.text}
        </p>
      )}
    </div>
  );
}
