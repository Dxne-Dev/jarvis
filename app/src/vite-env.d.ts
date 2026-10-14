/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OJARVIS_ENGINE_URL?: string;
  readonly VITE_OJARVIS_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
