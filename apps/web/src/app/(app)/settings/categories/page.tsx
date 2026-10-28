"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CornerDownRight, MoreHorizontal, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { CategorySelect, useCategories, useCategoryGroups, type CategoryValue } from "@/components/erp/category-select";
import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/input";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import type { Category, CategoryGroup } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = Category & { depth: number };

function toTree(categories: Category[]): Row[] {
  const children = new Map<string | null, Category[]>();
  for (const c of categories) children.set(c.parent_id ?? null, [...(children.get(c.parent_id ?? null) ?? []), c]);
  const ids = new Set(categories.map((c) => c.id));
  const out: Row[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const c of children.get(parent) ?? []) {
      out.push({ ...c, depth });
      walk(c.id, depth + 1);
    }
  };
  walk(null, 0);
  // Orphans (parent filtered out, e.g. inactive parent hidden) still show at the top level.
  for (const c of categories) if (c.parent_id && !ids.has(c.parent_id) && !out.some((r) => r.id === c.id)) out.push({ ...c, depth: 0 });
  return out;
}

function ConfigFields({
  schema,
  value,
  onChange,
}: {
  schema: Record<string, string>;
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const entries = Object.entries(schema);
  if (!entries.length) return null;
  return (
    <fieldset className="flex flex-col gap-3 rounded-md border p-3">
      <legend className="px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Settings</legend>
      {entries.map(([key, kind]) => {
        const id = `cfg-${key}`;
        const label = key.replaceAll("_", " ");
        const set = (v: unknown) => {
          const next = { ...value };
          if (v === "" || v === undefined || (Array.isArray(v) && !v.length)) delete next[key];
          else next[key] = v;
          onChange(next);
        };
        if (kind === "bool") {
          return (
            <label key={key} className="flex items-center gap-2 text-sm capitalize">
              <Checkbox checked={value[key] === true} onChange={(e) => set(e.target.checked || undefined)} />
              {label}
            </label>
          );
        }
        const current = value[key];
        return (
          <FormField key={key} id={id} label={label} hint={kind === "str_list" ? "Comma-separated" : kind === "uuid" ? "Set in Phase 2 when accounts exist" : undefined}>
            <Input
              id={id}
              value={Array.isArray(current) ? current.join(", ") : ((current as string) ?? "")}
              onChange={(e) =>
                set(kind === "str_list" ? e.target.value.split(",").map((s) => s.trim()).filter(Boolean) : e.target.value.trim())
              }
            />
          </FormField>
        );
      })}
    </fieldset>
  );
}

function CategoryDialog({
  group,
  categories,
  editing,
  parentId,
  onClose,
}: {
  group: CategoryGroup;
  categories: Category[];
  editing: Category | null;
  parentId: string | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState(editing?.name ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [parent, setParent] = useState<string | null>(editing ? editing.parent_id : parentId);
  const [config, setConfig] = useState<Record<string, unknown>>(editing?.config ?? {});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const parentOptions = categories.filter((c) => c.is_active && !c.merged_into_id && c.id !== editing?.id);

  const save = useMutation({
    mutationFn: () => {
      const body = { name, description: description || null, config };
      if (editing) {
        return api.patch<Category>(`/categories/${editing.id}`, {
          ...body,
          version: editing.version,
          ...(editing.is_system ? {} : { parent_id: parent }),
        });
      }
      return api.post<Category>("/categories", { ...body, group_key: group.key, parent_id: parent }, { idempotencyKey: newIdempotencyKey() });
    },
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["categories", group.key] });
      toast.success(editing ? "Category updated" : `“${c.name}” added`);
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        if (!err.errors.length) toast.error(err.message);
      }
    },
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? `Edit “${editing.name}”` : `New ${group.label.toLowerCase().replace(/s$/, "")}`}</DialogTitle>
          {editing?.is_system && (
            <DialogDescription>Built-in value: you can rename it, but it always stays at the top level.</DialogDescription>
          )}
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <FormField id="cat_name" label="Name" required error={errors.name}>
            <Input id="cat_name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} autoFocus />
          </FormField>
          {!editing?.is_system && (
            <FormField id="cat_parent" label="Parent" error={errors.parent_id} hint="Custom values usually sit under “Other”.">
              <Select id="cat_parent" value={parent ?? ""} onChange={(e) => setParent(e.target.value || null)}>
                <option value="">— top level —</option>
                {parentOptions.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.path}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
          <FormField id="cat_desc" label="Description">
            <Textarea id="cat_desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </FormField>
          <ConfigFields schema={group.config_schema} value={config} onChange={setConfig} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending} disabled={!name.trim()}>
              {editing ? "Save" : "Add"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MergeDialog({ source, categories, onClose }: { source: Category; categories: Category[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState("");
  const targets = categories.filter((c) => c.id !== source.id && c.is_active && !c.merged_into_id);
  const merge = useMutation({
    mutationFn: () => api.post<Category>(`/categories/${source.id}/merge`, { target_id: target }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories", source.group_key] });
      toast.success(`Merged “${source.name}”`);
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not merge"),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Merge “{source.name}”</DialogTitle>
          <DialogDescription>
            Use this for duplicates. Past records keep their original value; reports group them under the target. You can undo a merge.
          </DialogDescription>
        </DialogHeader>
        <FormField id="merge_target" label="Merge into">
          <Select id="merge_target" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Select…</option>
            {targets.map((c) => (
              <option key={c.id} value={c.id}>
                {c.path}
              </option>
            ))}
          </Select>
        </FormField>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!target} loading={merge.isPending} onClick={() => merge.mutate()}>
            Merge
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function GroupPanel({ group }: { group: CategoryGroup }) {
  const qc = useQueryClient();
  const [showInactive, setShowInactive] = useState(false);
  const categories = useCategories(group.key, showInactive);
  const all = useCategories(group.key, true);
  const [dialog, setDialog] = useState<{ editing: Category | null; parentId: string | null } | null>(null);
  const [merging, setMerging] = useState<Category | null>(null);
  const [deleting, setDeleting] = useState<Category | null>(null);
  const rows = useMemo(() => toTree(categories.data ?? []), [categories.data]);
  const nameOf = (id: string | null | undefined) => all.data?.find((c) => c.id === id)?.name;

  const action = useMutation({
    mutationFn: ({ c, op }: { c: Category; op: "activate" | "deactivate" | "unmerge" }) => api.post<Category>(`/categories/${c.id}/${op}`),
    onSuccess: (_, { op }) => {
      qc.invalidateQueries({ queryKey: ["categories", group.key] });
      toast.success({ activate: "Activated", deactivate: "Deactivated", unmerge: "Unmerged" }[op]);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Action failed"),
  });

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>{group.label}</CardTitle>
          <CardDescription>{group.description}</CardDescription>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <Checkbox checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
            Show inactive
          </label>
          {group.can_manage && (
            <Button size="sm" onClick={() => setDialog({ editing: null, parentId: null })}>
              <Plus /> Add
            </Button>
          )}
        </div>
      </CardHeader>
      {categories.isError ? (
        <ErrorState error={categories.error} onRetry={() => categories.refetch()} />
      ) : categories.isLoading ? (
        <TableSkeleton rows={5} />
      ) : rows.length === 0 ? (
        <EmptyState title="No categories" />
      ) : (
        <ul className="divide-y">
          {rows.map((c) => (
            <li key={c.id} className={cn("flex items-center gap-3 px-5 py-2.5", !c.is_active && "opacity-60")}>
              <div className="flex min-w-0 flex-1 items-center gap-2" style={{ paddingLeft: c.depth * 20 }}>
                {c.depth > 0 && <CornerDownRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                <span className="truncate font-medium">{c.name}</span>
                {c.is_system && <Badge variant="muted">Built-in</Badge>}
                {c.is_other && <Badge variant="outline">Other</Badge>}
                {!c.is_active && !c.merged_into_id && <Badge variant="warning">Inactive</Badge>}
                {c.merged_into_id && <Badge variant="warning">Merged into {nameOf(c.merged_into_id) ?? "…"}</Badge>}
                {c.description && <span className="hidden truncate text-sm text-muted-foreground md:inline">· {c.description}</span>}
              </div>
              {group.can_manage && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={`Actions for ${c.name}`}>
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    {c.merged_into_id ? (
                      <DropdownMenuItem onSelect={() => action.mutate({ c, op: "unmerge" })}>Undo merge</DropdownMenuItem>
                    ) : (
                      <>
                        <DropdownMenuItem onSelect={() => setDialog({ editing: c, parentId: c.parent_id ?? null })}>Edit</DropdownMenuItem>
                        {c.is_active && (
                          <DropdownMenuItem onSelect={() => setDialog({ editing: null, parentId: c.id })}>Add sub-category</DropdownMenuItem>
                        )}
                        {!c.is_system && c.is_active && <DropdownMenuItem onSelect={() => setMerging(c)}>Merge into…</DropdownMenuItem>}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onSelect={() => action.mutate({ c, op: c.is_active ? "deactivate" : "activate" })}>
                          {c.is_active ? "Deactivate" : "Activate"}
                        </DropdownMenuItem>
                        {!c.is_system && (
                          <DropdownMenuItem destructive onSelect={() => setDeleting(c)}>
                            Delete
                          </DropdownMenuItem>
                        )}
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </li>
          ))}
        </ul>
      )}
      {dialog && (
        <CategoryDialog group={group} categories={all.data ?? []} editing={dialog.editing} parentId={dialog.parentId} onClose={() => setDialog(null)} />
      )}
      {merging && <MergeDialog source={merging} categories={all.data ?? []} onClose={() => setMerging(null)} />}
      {deleting && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setDeleting(null)}
          title={`Delete “${deleting.name}”?`}
          description="Only categories that were never used can be deleted. Used ones should be deactivated or merged so history stays intact."
          confirmLabel="Delete"
          destructive
          onConfirm={async () => {
            try {
              await api.delete(`/categories/${deleting.id}`);
              qc.invalidateQueries({ queryKey: ["categories", group.key] });
              toast.success("Category deleted");
            } catch (err) {
              toast.error(err instanceof ApiError ? err.message : "Could not delete");
              throw err;
            }
          }}
        />
      )}
    </Card>
  );
}

function PickerPreview({ group }: { group: CategoryGroup }) {
  const [value, setValue] = useState<CategoryValue>({ category_id: null, other_text: "" });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Picker preview</CardTitle>
        <CardDescription>How this group appears on forms. Try choosing “Other”.</CardDescription>
      </CardHeader>
      <CardContent>
        <CategorySelect key={group.key} group={group.key} label={group.label.replace(/s$/, "")} value={value} onChange={setValue} />
      </CardContent>
    </Card>
  );
}

export default function CategoriesPage() {
  const groups = useCategoryGroups();
  const [selectedKey, setSelectedKey] = useState("payment_method");
  const selected = groups.data?.find((g) => g.key === selectedKey) ?? groups.data?.[0];

  if (groups.isError) return <ErrorState error={groups.error} onRetry={() => groups.refetch()} />;

  return (
    <>
      <PageHeader
        title="Custom categories"
        description="Classifications used across the system. Every group has an “Other” option so unusual cases can still be recorded, without skipping accounting rules."
      />
      <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
        <Card className="h-fit">
          <label htmlFor="group-select" className="sr-only">
            Category group
          </label>
          <Select id="group-select" className="m-3 w-[calc(100%-1.5rem)] lg:hidden" value={selected?.key} onChange={(e) => setSelectedKey(e.target.value)}>
            {groups.data?.map((g) => (
              <option key={g.key} value={g.key}>
                {g.label}
              </option>
            ))}
          </Select>
          <ul className="hidden p-2 lg:block">
            {groups.data?.map((g) => (
              <li key={g.key}>
                <button
                  type="button"
                  onClick={() => setSelectedKey(g.key)}
                  className={cn(
                    "w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted",
                    selected?.key === g.key && "bg-accent font-medium text-accent-foreground",
                  )}
                >
                  {g.label}
                </button>
              </li>
            ))}
          </ul>
        </Card>
        {selected ? (
          <div className="flex flex-col gap-6">
            <GroupPanel key={selected.key} group={selected} />
            <PickerPreview group={selected} />
          </div>
        ) : (
          <TableSkeleton />
        )}
      </div>
    </>
  );
}
