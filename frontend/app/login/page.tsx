'use client';

import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';

import { InlineAlert } from '../../components/ui/patterns';
import { Button, Field, Input, Subtitle, Title } from '../../components/ui/primitives';
import { api } from '../../lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await api.login(email, password);
      router.replace('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    }
  }

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Title kicker="Auth">Sign in</Title>
        <Subtitle>Use your crawler workspace credentials.</Subtitle>
      </div>
      <form className="grid gap-4" onSubmit={onSubmit}>
        <Field label="Email">
          <Input
            type="email"
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
            placeholder="••••••••"
          />
        </Field>
        {error ? <InlineAlert message={error} /> : null}
        <div className="pt-2">
          <Button type="submit" size="lg" className="w-full">
            Sign in
          </Button>
        </div>
      </form>
    </div>
  );
}
