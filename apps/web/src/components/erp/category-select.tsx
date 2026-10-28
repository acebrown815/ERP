"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox, Input, Select } from "@/components/ui/input";
import { Label } from "@/components/ui/misc";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import type { Category, CategoryGroup } from "@/lib/types";

export type CategoryValue = { category_id: string | null; other_text: string };

export function useCategories(group: string, includeInactive = false) {
  return useQuery({
    queryKey: ["categories", group, includeInactive],
    queryFn: () => api.get<Category[]>("/categories", { group, include_inactive: includeInactive }),
  });
}

export function useCategoryGroups() {
  return useQuery({
    queryKey: ["category-groups"],
    queryFn: () => api.get<CategoryGroup[]>("/categories/groups"),
    staleTime: 5 * 60_000,
  });
}

/**
 * Picker with the platform-wide "Other" behaviour (docs/architecture.md, Section 12.2):
 * pick a standard value, or "Other" and then either a saved custom value or a one-off description.
 * "Save for reuse" turns the description into a sub-category under Other (if the user may manage the group).
 */
export function CategorySelect({
  group,
  value,
  onChange,
  label,
  error,
  required,
}: {
  group: string;
  value: CategoryValue;
  onChange: (value: CategoryValue) => void;
  label: string;
  error?: string;
  required?: boolean;
}) {
  const id = useId();
  const qc = useQueryClient();
  const { data: categories = [], isLoading } = useCategories(group);
  const { data: groups = [] } = useCategoryGroups();
  const canManage = groups.find((g) => g.key === group)?.can_manage ?? false;
  const [saveForReuse, setSaveForReuse] = useState(false);

  const other = categories.find((c) => c.is_other && c.parent_id === null);
  const otherChildren = useMemo(
    () => (other ? categories.filter((c) => c.parent_id === other.id) : []),
    [categories, other],
  );
  const mainOptions = categories.filter((c) => !other || c.parent_id !== other.id);

  const selected = categories.find((c) => c.id === value.category_id);
  const underOther = !!selected && !!other && (selected.id === other.id || selected.parent_id === other.id);
  const mainValue = underOther ? other!.id : (value.category_id ?? "");

  const create = useMutation({
    mutationFn: (name: string) =>
      api.post<Category>(
        "/categories",
        { group_key: group, name, parent_id: other?.id },
        { idempotencyKey: newIdempotencyKey() },
      ),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["categories", group] });
      onChange({ category_id: created.id, other_text: "" });
      setSaveForReuse(false);
      toast.success(`Saved “${created.name}” for reuse`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not save category"),
  });

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required && <span className="ml-0.5 text-destructive" aria-hidden>*</span>}
      </Label>
      <Select
        id={id}
        value={mainValue}
        disabled={isLoading}
        aria-invalid={!!error}
        onChange={(e) => onChange({ category_id: e.target.value || null, other_text: "" })}
      >
        <option value="">{isLoading ? "Loading…" : "Select…"}</option>
        {mainOptions.map((c) => (
          <option key={c.id} value={c.id}>
            {c.path}
          </option>
        ))}
      </Select>

      {underOther && other && (
        <div className="mt-1 flex flex-col gap-2 rounded-md border border-dashed bg-muted/40 p-3">
          {otherChildren.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-saved`} className="text-xs text-muted-foreground">
                Saved custom value
              </Label>
              <Select
                id={`${id}-saved`}
                value={selected?.parent_id === other.id ? selected.id : ""}
                onChange={(e) => onChange({ category_id: e.target.value || other.id, other_text: "" })}
              >
                <option value="">— none, describe below —</option>
                {otherChildren.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
          )}
          {selected?.id === other.id && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-other`} className="text-xs text-muted-foreground">
                  Describe “Other”<span className="ml-0.5 text-destructive" aria-hidden>*</span>
                </Label>
                <Input
                  id={`${id}-other`}
                  value={value.other_text}
                  maxLength={120}
                  placeholder="e.g. Wise Transfer"
                  aria-invalid={!!error && !value.other_text.trim()}
                  onChange={(e) => onChange({ category_id: other.id, other_text: e.target.value })}
                />
              </div>
              {canManage && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox checked={saveForReuse} onChange={(e) => setSaveForReuse(e.target.checked)} />
                    Save for reuse
                  </label>
                  {saveForReuse && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!value.other_text.trim()}
                      loading={create.isPending}
                      onClick={() => create.mutate(value.other_text.trim())}
                    >
                      Save as category
                    </Button>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
