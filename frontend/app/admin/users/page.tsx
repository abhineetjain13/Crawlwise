"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../../../lib/api";
import type { Paginated, User } from "../../../lib/api/types";
import { formatAdminUserDate as formatDate } from "../../../lib/format/date";
import { Badge, Card, Input } from "../../../components/ui/primitives";
import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  SectionHeader,
  TableSurface,
} from "../../../components/ui/patterns";

type StatusFilter = "all" | "active" | "inactive";

export default function AdminUsersPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [updateError, setUpdateError] = useState("");
  const usersQuery = useQuery<Paginated<User>>({
    queryKey: ["users", search, status],
    queryFn: () =>
      api.listUsers({
        search: search.trim() || undefined,
        is_active: status === "all" ? undefined : status === "active",
      }),
  });

  const users = useMemo(() => usersQuery.data?.items ?? [], [usersQuery.data?.items]);
  const counts = useMemo(
    () => ({
      total: usersQuery.data?.meta?.total ?? users.length,
      active: users.filter((user) => user.is_active).length,
      inactive: users.filter((user) => !user.is_active).length,
    }),
    [users, usersQuery.data?.meta?.total],
  );

  async function updateUser(userId: number, payload: Partial<Pick<User, "role" | "is_active">>) {
    setPendingUserId(userId);
    try {
      setUpdateError("");
      await api.updateUser(userId, payload);
      await usersQuery.refetch();
    } catch (error) {
      setUpdateError(error instanceof Error ? error.message : "Unable to update user.");
    } finally {
      setPendingUserId(null);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Users" description="Manage roles and account status." />

      <div className="grid gap-3 md:grid-cols-3">
        <MetricCard label="Total" value={counts.total} />
        <MetricCard label="Active" value={counts.active} />
        <MetricCard label="Inactive" value={counts.inactive} />
      </div>

      <Card className="space-y-4">
        <SectionHeader title="User Management" description="Filter by email and status." />
        <div className="flex flex-col gap-2 lg:flex-row">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by email"
            className="lg:max-w-sm"
          />
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as StatusFilter)}
            className="control-select focus-ring"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        {updateError ? <InlineAlert message={updateError} /> : null}

        {usersQuery.isLoading ? (
          <DataRegionLoading count={6} />
        ) : users.length ? (
          <TableSurface className="border border-border bg-transparent shadow-none">
            <table className="compact-data-table min-w-[840px]">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Registered</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td className="text-data-strong">{user.email}</td>
                    <td>
                      <select
                        value={user.role}
                        onChange={(event) => {
                          const role = event.target.value as User["role"];
                          if (role === "user" || role === "admin") {
                            void updateUser(user.id, { role });
                          }
                        }}
                        disabled={pendingUserId === user.id}
                        className="control-select focus-ring min-w-24"
                      >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
                    </td>
                    <td>
                      <Badge tone={user.is_active ? "success" : "danger"}>
                        {user.is_active ? "active" : "inactive"}
                      </Badge>
                    </td>
                    <td className="text-body-sm text-muted">{formatDate(user.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        disabled={pendingUserId === user.id}
                        onClick={() => void updateUser(user.id, { is_active: !user.is_active })}
                        className="focus-ring h-8 rounded-[var(--radius-md)] border border-border bg-transparent px-3 text-link-ui text-foreground transition hover:bg-background-elevated disabled:opacity-40"
                      >
                        {user.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableSurface>
        ) : (
          <DataRegionEmpty title="No users found" description="Adjust the filters to broaden the result set." className="px-0" />
        )}
      </Card>
    </div>
  );
}

function MetricCard({ label, value }: Readonly<{ label: string; value: number }>) {
  return (
    <div className="surface-panel p-4">
      <div className="label-caps">{label}</div>
      <div className="mt-1 text-title-md text-primary">{value}</div>
    </div>
  );
}
