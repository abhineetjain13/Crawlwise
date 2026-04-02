"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { Button, Card, Field, Input, Title } from "../../../components/ui/primitives";
import { api } from "../../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await api.login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Card className="space-y-6">
        <div className="space-y-3">
          <Title kicker="Auth">Login</Title>
          <p className="text-sm text-muted">Enter your credentials.</p>
        </div>
        <form className="grid gap-5" onSubmit={onSubmit}>
          <Field label="Email">
            <Input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" />
          </Field>
          <Field label="Password">
            <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="••••••••" />
          </Field>
          {error ? <p className="rounded-2xl bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">{error}</p> : null}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit">Login</Button>
            <Link className="text-sm font-medium text-brand" href="/register">
              Create account
            </Link>
          </div>
        </form>
      </Card>
    </div>
  );
}
