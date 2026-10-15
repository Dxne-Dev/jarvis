import type { ComponentProps } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { openExternal } from "../lib/links";

/** Un lien venu d'un texte de modèle : ouvert dans le navigateur, jamais dans l'app. */
export function ExternalLink({ href, children }: ComponentProps<"a">) {
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

/** Du markdown écrit par un modèle : sans HTML brut, liens ouverts dehors. */
export function RichText({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className}>
      <Markdown remarkPlugins={[remarkGfm]} components={{ a: ExternalLink }}>
        {text}
      </Markdown>
    </div>
  );
}
