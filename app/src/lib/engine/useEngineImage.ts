import { useEffect, useState } from "react";

import { useEngineStore } from "./store";

/** Une image lue sur le moteur de cette machine (avec le jeton), en adresse locale ; `null`
 * tant qu'elle n'est pas arrivée. `version` change : l'image est relue. */
export function useEngineImage(path: string | null, version: unknown = null): string | null {
  const client = useEngineStore((s) => s.client);
  const [image, setImage] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !path) return;
    let cancelled = false;
    void client
      .blob(path)
      .then((blob) => {
        if (cancelled || !blob) return;
        const next = URL.createObjectURL(blob);
        setImage((previous) => {
          if (previous) URL.revokeObjectURL(previous);
          return next;
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true; // une version plus récente est déjà demandée
    };
  }, [client, path, version]);

  useEffect(
    () => () => {
      setImage((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return null;
      });
    },
    [],
  );

  return image;
}
