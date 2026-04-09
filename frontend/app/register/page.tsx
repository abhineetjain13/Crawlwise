"use client";

import Link from "next/link";

import { InlineAlert } from "../../components/ui/patterns";
import { Subtitle, Title } from "../../components/ui/primitives";

export default function RegisterPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Title kicker="Auth">Register</Title>
        <Subtitle>Account creation is turned off in this development build.</Subtitle>
      </div>
      <InlineAlert message="Use the bootstrap admin account from your backend environment (BOOTSTRAP_ADMIN_ONCE, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD). Public registration will be re-enabled for production multi-tenant deployments." />
      <div>
        <Link className="text-[13px] font-medium text-accent" href="/login">
          Back to sign in
        </Link>
      </div>
    </div>
  );
}
