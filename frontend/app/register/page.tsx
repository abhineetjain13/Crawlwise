"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { InlineAlert } from "../../components/ui/patterns";
import { Button, Field, Input, Subtitle, Title } from "../../components/ui/primitives";
import { api } from "../../lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await api.register(email, password);
      await api.login(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Register failed");
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Title kicker="Auth">Register</Title>
        <Subtitle>Create a workspace account.</Subtitle>
      </div>
      <form className="grid gap-5" onSubmit={onSubmit}>
        <Field label="Email">
          <Input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@company.com"
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Choose a secure password"
          />
        </Field>
        {error ? <InlineAlert message={error} /> : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit">Create account</Button>
          <Link className="text-[13px] font-medium text-accent" href="/login">
            Back to login
          </Link>
        </div>
      </form>
    </div>
  );
}
