import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";

import { EngineUnreachableError } from "../lib/engine/client";
import { EngineProvider } from "../lib/engine/EngineProvider";
import { router } from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
      retry: (failures, error) => error instanceof EngineUnreachableError && failures < 3,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <EngineProvider>
        <RouterProvider router={router} />
      </EngineProvider>
    </QueryClientProvider>
  );
}
