import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Board } from "@/components/Board.tsx";

export function App(): React.JSX.Element {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: true, staleTime: 1000 } } }));
  return (
    <QueryClientProvider client={client}>
      <Board />
    </QueryClientProvider>
  );
}
