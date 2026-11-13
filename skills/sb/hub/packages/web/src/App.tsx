import { useState } from "react";
import { Button } from "@/components/ui/button";

export function App(): React.JSX.Element {
  const [clicks, setClicks] = useState(0);
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">sb hub</h1>
      <p className="text-sm text-neutral-500">Placeholder page for the typed board.</p>
      <Button onClick={() => { setClicks(clicks + 1); }}>Clicked {clicks} times</Button>
    </main>
  );
}
