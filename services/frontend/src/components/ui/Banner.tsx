import type { ReactNode } from "react";
import { errorToMessages } from "@/lib/errors";

export function ErrorBanner({ title, error }: { title?: string; error: unknown }) {
  const messages = errorToMessages(error);
  return (
    <div className="rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
      {title && <div className="mb-1 font-semibold">{title}</div>}
      <ul className="list-disc space-y-0.5 pl-5">
        {messages.map((message, index) => (
          <li key={index}>{message}</li>
        ))}
      </ul>
    </div>
  );
}

export function SuccessBanner({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-success/30 bg-success/10 px-4 py-2 text-sm text-success">
      {children}
    </div>
  );
}
