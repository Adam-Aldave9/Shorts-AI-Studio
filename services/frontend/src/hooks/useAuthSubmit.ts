import { useState } from "react";

/** Submit state machine shared by the Login/Register forms: tracks pending + error and
 *  runs the auth action inside a try/catch/finally. */
export function useAuthSubmit(action: () => Promise<void>) {
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  async function submit() {
    setPending(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return { error, pending, submit };
}
