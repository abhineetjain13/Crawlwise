'use client';

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { api } from '../../../lib/api';
import type { Paginated, User } from '../../../lib/api/types';
import { formatAdminUserDate as formatDate } from '../../../lib/format/date';
import { Badge, Button, Dropdown, Input, Metric } from '../../../components/ui/primitives';
import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  SectionCard,
  TableSurface,
} from '../../../components/ui/patterns';

type StatusFilter = 'all' | 'active' | 'inactive';

export default function AdminUsersPage() {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [updateError, setUpdateError] = useState('');
  const usersQuery = useQuery<Paginated<User>>({
    queryKey: ['users', search, status],
    queryFn: () =>
      api.listUsers({
        search: search.trim() || undefined,
        is_active: status === 'all' ? undefined : status === 'active',
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

  async function updateUser(userId: number, payload: Partial<Pick<User, 'role' | 'is_active'>>) {
    setPendingUserId(userId);
    try {
      setUpdateError('');
      await api.updateUser(userId, payload);
      await usersQuery.refetch();
    } catch (error) {
      setUpdateError(error instanceof Error ? error.message : 'Unable to update user.');
    } finally {
      setPendingUserId(null);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader title="Users" description="Manage roles and account status." />

      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="Total" value={counts.total} />
        <Metric label="Active" value={counts.active} />
        <Metric label="Inactive" value={counts.inactive} />
      </div>

      <SectionCard title="User Management" description="Filter by email and status.">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex-1">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by email"
            />
          </div>
          <Dropdown<StatusFilter>
            value={status}
            onChange={setStatus}
            options={[
              { value: 'all', label: 'All Statuses' },
              { value: 'active', label: 'Active' },
              { value: 'inactive', label: 'Inactive' },
            ]}
            className="sm:min-w-[180px]"
          />
        </div>
        {updateError ? <InlineAlert message={updateError} /> : null}
        {usersQuery.error ? (
          <InlineAlert
            message={
              usersQuery.error instanceof Error ? usersQuery.error.message : 'Failed to load users.'
            }
          />
        ) : null}

        {usersQuery.isLoading ? (
          <DataRegionLoading count={6} />
        ) : users.length ? (
          <TableSurface className="table-surface-flat">
            <table className="compact-data-table min-w-[840px]">
              <colgroup>
                <col style={{ width: '40%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
              </colgroup>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Joined</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td className="text-foreground text-sm leading-[var(--leading-normal)] font-normal">
                      {user.email}
                    </td>
                    <td>
                      <Dropdown<User['role']>
                        value={user.role}
                        onChange={(role) => {
                          void updateUser(user.id, { role });
                        }}
                        disabled={pendingUserId === user.id}
                        options={[
                          { value: 'user', label: 'user' },
                          { value: 'harness', label: 'harness' },
                          { value: 'admin', label: 'admin' },
                        ]}
                        className="min-w-24"
                      />
                    </td>
                    <td>
                      <Badge tone={user.is_active ? 'success' : 'danger'}>
                        {user.is_active ? 'active' : 'inactive'}
                      </Badge>
                    </td>
                    <td className="text-muted text-sm leading-[var(--leading-relaxed)]">
                      {formatDate(user.created_at)}
                    </td>
                    <td className="text-right">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={pendingUserId === user.id}
                        onClick={() => void updateUser(user.id, { is_active: !user.is_active })}
                        className="min-w-[96px]"
                      >
                        {user.is_active ? 'Deactivate' : 'Reactivate'}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableSurface>
        ) : (
          <DataRegionEmpty
            title="No users found"
            description="Adjust the filters to broaden the result set."
            className="px-0"
          />
        )}
      </SectionCard>
    </div>
  );
}
