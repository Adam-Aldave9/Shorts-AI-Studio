import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui";
import { Logo } from "@/components/Logo";

/** Centered card layout shared by the Login and Register screens. */
export function AuthScreen({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link to="/" className="mb-6">
        <Logo withWordmark />
      </Link>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-1 text-sm text-fg-muted">{subtitle}</p>
      <Card className="mt-6">{children}</Card>
      <p className="mt-4 text-center text-sm text-fg-muted">{footer}</p>
    </div>
  );
}
