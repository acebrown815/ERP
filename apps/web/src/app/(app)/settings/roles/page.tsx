"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import type { Permission, Role } from "@/lib/types";
import { cn } from "@/lib/utils";

const SCOPE_LABEL: Record<string, string> = {
  own: "Own records",
  project: "Their projects",
  all: "Everything",
};

function NewRoleDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (r: Role) => void }) {
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () => api.post<Role>("/roles", { key, name, description: description || null, grants: {} }),
    onSuccess: (role) => {
      onCreated(role);
      onOpenChange(false);
      setName("");
      setKey("");
      setDescription("");
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        if (!err.errors.length) toast.error(err.message);
      }
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New role</DialogTitle>
          <DialogDescription>Create the role, then choose its permissions.</DialogDescription>
        </DialogHeader>
        <FormField id="role_name" label="Name" required error={errors.name}>
          <Input
            id="role_name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setKey(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 50));
            }}
          />
        </FormField>
        <FormField id="role_key" label="Key" hint="Lowercase letters, digits and underscores." error={errors.key}>
          <Input id="role_key" value={key} onChange={(e) => setKey(e.target.value)} className="font-mono" />
        </FormField>
        <FormField id="role_desc" label="Description">
          <Textarea id="role_desc" value={description} onChange={(e) => setDescription(e.target.value)} />
        </FormField>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={!name || !key} onClick={() => create.mutate()}>
            Create role
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function GrantEditor({ role, permissions }: { role: Role; permissions: Permission[] }) {
  const qc = useQueryClient();
  const [grants, setGrants] = useState<Record<string, string>>(role.grants);
  useEffect(() => setGrants(role.grants), [role]);
  const dirty = JSON.stringify(grants) !== JSON.stringify(role.grants);

  const groups = useMemo(() => {
    const out = new Map<string, Permission[]>();
    for (const p of permissions) out.set(p.group, [...(out.get(p.group) ?? []), p]);
    return [...out.entries()];
  }, [permissions]);

  const save = useMutation({
    mutationFn: () => api.patch<Role>(`/roles/${role.id}`, { grants }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
      toast.success(`Permissions for ${role.name} saved. They apply on the next request.`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not save"),
  });

  if (role.grants_all) {
    return (
      <div className="flex items-start gap-3 rounded-md border bg-muted/40 p-4 text-sm">
        <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <p>The Administrator role always has every permission, including ones added in future releases.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {groups.map(([group, perms]) => (
        <section key={group}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group}</h3>
          <ul className="divide-y rounded-md border">
            {perms.map((p) => (
              <li key={p.key} className="flex flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="text-sm">{p.label}</div>
                  <div className="font-mono text-xs text-muted-foreground">{p.key}</div>
                </div>
                <Select
                  aria-label={`Scope for ${p.label}`}
                  className={cn("sm:w-44", grants[p.key] && "border-primary/50 bg-accent/40")}
                  value={grants[p.key] ?? ""}
                  onChange={(e) => {
                    const next = { ...grants };
                    if (e.target.value) next[p.key] = e.target.value;
                    else delete next[p.key];
                    setGrants(next);
                  }}
                >
                  <option value="">No access</option>
                  {p.scopes.map((s) => (
                    <option key={s} value={s}>
                      {SCOPE_LABEL[s] ?? s}
                    </option>
                  ))}
                </Select>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-card py-3">
        <Button variant="outline" disabled={!dirty} onClick={() => setGrants(role.grants)}>
          Discard
        </Button>
        <Button disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          Save permissions
        </Button>
      </div>
    </div>
  );
}

export default function RolesPage() {
  const qc = useQueryClient();
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api.get<Role[]>("/roles") });
  const permissions = useQuery({ queryKey: ["permissions"], queryFn: () => api.get<Permission[]>("/permissions"), staleTime: Infinity });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Role | null>(null);

  const selected = roles.data?.find((r) => r.id === selectedId) ?? roles.data?.[0];

  if (roles.isError) return <ErrorState error={roles.error} onRetry={() => roles.refetch()} />;

  return (
    <>
      <PageHeader
        title="Roles & permissions"
        description="Each permission is granted with a scope: own records, the projects someone works on, or everything."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> New role
          </Button>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card className="h-fit">
          {roles.isLoading ? (
            <TableSkeleton rows={4} />
          ) : (
            <ul className="p-2">
              {roles.data!.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(r.id)}
                    className={cn(
                      "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-muted",
                      selected?.id === r.id && "bg-accent text-accent-foreground",
                    )}
                  >
                    <span className="font-medium">{r.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {r.user_count} user{r.user_count === 1 ? "" : "s"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {selected && (
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4">
              <div>
                <CardTitle className="flex items-center gap-2">
                  {selected.name} {selected.is_system && <Badge variant="muted">System</Badge>}
                </CardTitle>
                {selected.description && <CardDescription>{selected.description}</CardDescription>}
              </div>
              {!selected.is_system && (
                <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setDeleting(selected)}>
                  <Trash2 /> Delete
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {permissions.data ? <GrantEditor role={selected} permissions={permissions.data} /> : <TableSkeleton />}
            </CardContent>
          </Card>
        )}
      </div>
      <NewRoleDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(r) => {
          qc.invalidateQueries({ queryKey: ["roles"] });
          setSelectedId(r.id);
          toast.success(`Role ${r.name} created`);
        }}
      />
      {deleting && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setDeleting(null)}
          title={`Delete ${deleting.name}?`}
          description={deleting.user_count ? `It is assigned to ${deleting.user_count} user(s); unassign it first.` : "This cannot be undone."}
          confirmLabel="Delete role"
          destructive
          onConfirm={async () => {
            try {
              await api.delete(`/roles/${deleting.id}`);
              qc.invalidateQueries({ queryKey: ["roles"] });
              setSelectedId(null);
              toast.success("Role deleted");
            } catch (err) {
              toast.error(err instanceof ApiError ? err.message : "Could not delete role");
              throw err;
            }
          }}
        />
      )}
    </>
  );
}
