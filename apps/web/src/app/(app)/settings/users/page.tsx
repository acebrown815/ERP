"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/erp/data-table";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Checkbox, Input } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/session";
import type { Page, Role, User } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const PAGE_SIZE = 25;

function useRoles() {
  return useQuery({ queryKey: ["roles"], queryFn: () => api.get<Role[]>("/roles") });
}

function RolePicker({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const roles = useRoles();
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 text-sm font-medium">Roles</legend>
      {(roles.data ?? []).map((r) => (
        <label key={r.id} className="flex items-start gap-2 text-sm">
          <Checkbox
            className="mt-0.5"
            checked={value.includes(r.id)}
            onChange={(e) => onChange(e.target.checked ? [...value, r.id] : value.filter((v) => v !== r.id))}
          />
          <span>
            <span className="font-medium">{r.name}</span>
            {r.description && <span className="block text-xs text-muted-foreground">{r.description}</span>}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

const createSchema = z.object({
  full_name: z.string().min(1, "Required"),
  email: z.string().email("Enter a valid email"),
  password: z.string().min(10, "Use at least 10 characters"),
});

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const form = useForm<z.infer<typeof createSchema>>({
    resolver: zodResolver(createSchema),
    defaultValues: { full_name: "", email: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await api.post<User>("/users", { ...values, role_ids: roleIds });
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(`${values.full_name} can now sign in`);
      form.reset();
      setRoleIds([]);
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError) {
        Object.entries(err.fieldErrors()).forEach(([f, m]) => form.setError(f as "email", { message: m }));
        if (!err.errors.length) toast.error(err.message);
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New user</DialogTitle>
          <DialogDescription>Share the temporary password privately; they can change it after signing in.</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <FormField id="full_name" label="Full name" required error={errors.full_name?.message}>
            <Input id="full_name" {...form.register("full_name")} />
          </FormField>
          <FormField id="new_email" label="Email" required error={errors.email?.message}>
            <Input id="new_email" type="email" autoComplete="off" {...form.register("email")} />
          </FormField>
          <FormField id="new_password" label="Temporary password" required error={errors.password?.message}>
            <Input id="new_password" type="password" autoComplete="new-password" {...form.register("password")} />
          </FormField>
          <RolePicker value={roleIds} onChange={setRoleIds} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={isSubmitting}>
              Create user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditUserDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient();
  const me = useMe();
  const isSelf = user.id === me.id;
  const [fullName, setFullName] = useState(user.full_name);
  const [roleIds, setRoleIds] = useState(user.roles.map((r) => r.id));
  const save = useMutation({
    mutationFn: () =>
      api.patch<User>(`/users/${user.id}`, {
        version: user.version,
        full_name: fullName,
        ...(isSelf ? {} : { role_ids: roleIds }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("User updated");
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not save"),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit {user.full_name}</DialogTitle>
          <DialogDescription>{user.email}</DialogDescription>
        </DialogHeader>
        <FormField id="edit_name" label="Full name">
          <Input id="edit_name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </FormField>
        {isSelf ? (
          <p className="text-sm text-muted-foreground">You can&apos;t change your own roles. Ask another administrator.</p>
        ) : (
          <RolePicker value={roleIds} onChange={setRoleIds} />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const reset = useMutation({
    mutationFn: () => api.post(`/users/${user.id}/set-password`, { password }),
    onSuccess: () => {
      toast.success("Password reset. Their sessions were signed out.");
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not reset password"),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset password</DialogTitle>
          <DialogDescription>Set a temporary password for {user.full_name}. This also unlocks the account.</DialogDescription>
        </DialogHeader>
        <FormField id="reset_pw" label="New password" hint="At least 10 characters.">
          <Input id="reset_pw" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </FormField>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={reset.isPending} disabled={password.length < 10} onClick={() => reset.mutate()}>
            Reset password
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function UsersPage() {
  const me = useMe();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);

  const users = useQuery({
    queryKey: ["users", page, q],
    queryFn: () => api.get<Page<User>>("/users", { page, page_size: PAGE_SIZE, q }),
    placeholderData: keepPreviousData,
  });

  const toggleActive = useMutation({
    mutationFn: (u: User) => api.patch<User>(`/users/${u.id}`, { version: u.version, is_active: !u.is_active }),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(u.is_active ? `${u.full_name} reactivated` : `${u.full_name} deactivated and signed out`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not update user"),
  });

  const columns = useMemo<ColumnDef<User, unknown>[]>(
    () => [
      {
        accessorKey: "full_name",
        header: "Name",
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.full_name}</div>
            <div className="text-xs text-muted-foreground">{row.original.email}</div>
          </div>
        ),
      },
      {
        id: "roles",
        header: "Roles",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.roles.length ? (
              row.original.roles.map((r) => <Badge key={r.id}>{r.name}</Badge>)
            ) : (
              <span className="text-xs text-muted-foreground">No roles</span>
            )}
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        accessorFn: (u) => (u.is_active ? (u.is_locked ? 1 : 0) : 2),
        cell: ({ row }) =>
          !row.original.is_active ? (
            <Badge variant="muted">Inactive</Badge>
          ) : row.original.is_locked ? (
            <Badge variant="warning">Locked</Badge>
          ) : (
            <Badge variant="success">Active</Badge>
          ),
      },
      {
        accessorKey: "last_login_at",
        header: "Last sign-in",
        cell: ({ row }) => <span className="text-muted-foreground">{formatDateTime(row.original.last_login_at)}</span>,
      },
      {
        id: "actions",
        header: "",
        size: 48,
        enableSorting: false,
        cell: ({ row }) => {
          const u = row.original;
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={`Actions for ${u.full_name}`}>
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onSelect={() => setEditing(u)}>Edit</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setResetting(u)}>Reset password</DropdownMenuItem>
                {u.id !== me.id && (
                  <DropdownMenuItem destructive={u.is_active} onSelect={() => toggleActive.mutate(u)}>
                    {u.is_active ? "Deactivate" : "Reactivate"}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          );
        },
      },
    ],
    [me.id, toggleActive],
  );

  return (
    <>
      <PageHeader
        title="Users"
        description="People who can sign in. Their roles decide what they can see and do."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> New user
          </Button>
        }
      />
      <Card>
        <div className="border-b p-3">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input
              aria-label="Search users"
              placeholder="Search name or email"
              className="pl-8"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>
        <DataTable
          columns={columns}
          data={users.data?.items}
          isLoading={users.isLoading}
          error={users.error}
          onRetry={() => users.refetch()}
          getRowId={(u) => u.id}
          pagination={users.data && { page, pageSize: PAGE_SIZE, total: users.data.total, onPageChange: setPage }}
        />
      </Card>
      <CreateUserDialog open={creating} onOpenChange={setCreating} />
      {editing && <EditUserDialog user={editing} onClose={() => setEditing(null)} />}
      {resetting && <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />}
    </>
  );
}
