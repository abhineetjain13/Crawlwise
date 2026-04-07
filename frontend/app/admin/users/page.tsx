"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../../../lib/api";
import type { User } from "../../../lib/api/types";
import { Badge, Card, Input } from "../../../components/ui/primitives";
import { EmptyPanel, PageHeader, SectionHeader } from "../../../components/ui/patterns";

type StatusFilter = "all" | "active" | "inactive";

/**
 * Renders the admin users management page with search, status filtering, role changes, and activation controls.
 * @example
 * AdminUsersPage()
 * <AdminUsersPage />
 * @param {undefined} Argument - This component does not accept any arguments.
 * @returns {JSX.Element} The admin users management page UI.
 */
export default function AdminUsersPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [updateError, setUpdateError] = useState("");
  const usersQuery = useQuery({
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

  /**
  * Updates a user's role or active status, refreshes the users list, and manages loading/error state.
  * @example
  * updateUser(123, { role: "admin", is_active: true })
  * undefined
  * @param {number} userId - The ID of the user to update.
  * @param {Partial<Pick<User, "role" | "is_active">>} payload - An object containing the user fields to update.
  * @returns {Promise<void>} A promise that resolves when the update and refetch operations complete.
  **/
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
        {updateError ? <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{updateError}</div> : null}

        {usersQuery.isLoading ? (
          <div className="rounded-[10px] border border-border bg-panel px-4 py-8 text-center text-sm text-muted">
            Loading users...
          </div>
        ) : users.length ? (
          <div className="overflow-auto rounded-[10px] border border-border">
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
                    <td className="font-medium text-foreground">{user.email}</td>
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
                    <td className="text-sm text-muted">{formatDate(user.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        disabled={pendingUserId === user.id}
                        onClick={() => void updateUser(user.id, { is_active: !user.is_active })}
                        className="focus-ring h-8 rounded-[var(--radius-md)] border border-border bg-transparent px-3 text-xs font-medium text-foreground transition hover:bg-background-elevated disabled:opacity-40"
                      >
                        {user.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyPanel title="No users found" description="Adjust the filters to broaden the result set." />
        )}
      </Card>
    </div>
  );
}

function MetricCard({ label, value }: Readonly<{ label: string; value: number }>) {
  return (
    <div className="rounded-[10px] border border-border bg-panel p-4 shadow-[var(--shadow-sm)]">
      <div className="label-caps">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-[var(--tracking-tight)]">{value}</div>
    </div>
  );
}

/**
 * Formats a date string into a localized, human-readable date and time, or returns the original value if invalid.
 * @example
 * formatDate("2024-01-15T10:30:00Z")
 * "Jan 15, 2024, 10:30 AM"
 * @param {string} value - The date string to format.
 * @returns {string} The formatted date string, or the original value if it cannot be parsed as a valid date.
 */
function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
