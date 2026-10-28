"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { CategorySelect } from "@/components/erp/category-select";
import { Combobox } from "@/components/erp/combobox";
import { FormField } from "@/components/erp/form-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { useCurrencies } from "@/lib/queries";
import type { Organization, Party } from "@/lib/types";

export type PartyKind = "customer" | "supplier" | "other";
export const KIND_LABEL: Record<PartyKind, { one: string; many: string }> = {
  customer: { one: "Customer", many: "Customers" },
  supplier: { one: "Supplier", many: "Suppliers" },
  other: { one: "Other party", many: "Other parties" },
};

export function PartyDialog({ kind, party, onClose }: { kind: PartyKind; party: Party | null; onClose: () => void }) {
  const qc = useQueryClient();
  const currencies = useCurrencies();
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: () => api.get<Organization[]>("/organizations") });
  const [form, setForm] = useState({
    name: party?.name ?? "",
    contact_name: party?.contact_name ?? "",
    email: party?.email ?? "",
    phone: party?.phone ?? "",
    website: party?.website ?? "",
    default_currency: party?.default_currency ?? "",
    notes: party?.notes ?? "",
    organization_id: party?.organization_id ?? null,
    subtype: { category_id: party?.subtype_category_id ?? null, other_text: party?.subtype_other_text ?? "" },
  });
  const [newOrg, setNewOrg] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name,
        contact_name: form.contact_name || null,
        email: form.email || null,
        phone: form.phone || null,
        website: form.website || null,
        default_currency: form.default_currency || null,
        notes: form.notes || null,
        organization_id: form.organization_id,
        subtype_category_id: kind === "other" ? form.subtype.category_id : null,
        subtype_other_text: kind === "other" ? form.subtype.other_text || null : null,
      };
      return party ? api.patch<Party>(`/parties/${party.id}`, { ...body, version: party.version }) : api.post<Party>("/parties", { ...body, kind });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["parties"] });
      qc.setQueryData(["party", p.id], p);
      toast.success(party ? "Saved" : `${p.name} added (${p.number})`);
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        if (!err.errors.length) toast.error(err.message);
      }
    },
  });
  const createOrg = useMutation({
    mutationFn: () => api.post<Organization>("/organizations", { legal_name: newOrg }),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["organizations"] });
      set("organization_id", o.id);
      setNewOrg("");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not create"),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{party ? `Edit ${party.name}` : `New ${KIND_LABEL[kind].one.toLowerCase()}`}</DialogTitle>
        </DialogHeader>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <FormField id="p_name" label="Name" required error={errors.name} className="sm:col-span-2">
            <Input id="p_name" value={form.name} onChange={(e) => set("name", e.target.value)} autoFocus />
          </FormField>
          {kind === "other" && (
            <div className="sm:col-span-2">
              <CategorySelect group="party_subtype" label="Kind of party" value={form.subtype} onChange={(v) => set("subtype", v)}
                error={errors.subtype_category_id ?? errors.subtype_other_text} />
            </div>
          )}
          <FormField id="p_contact" label="Contact person"><Input id="p_contact" value={form.contact_name} onChange={(e) => set("contact_name", e.target.value)} /></FormField>
          <FormField id="p_email" label="Email" error={errors.email}><Input id="p_email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} /></FormField>
          <FormField id="p_phone" label="Phone"><Input id="p_phone" value={form.phone} onChange={(e) => set("phone", e.target.value)} /></FormField>
          <FormField id="p_web" label="Website"><Input id="p_web" value={form.website} onChange={(e) => set("website", e.target.value)} /></FormField>
          <FormField id="p_cur" label="Default currency" error={errors.default_currency}>
            <Select id="p_cur" value={form.default_currency} onChange={(e) => set("default_currency", e.target.value)}>
              <option value="">—</option>
              {currencies.data?.map((c) => <option key={c.code} value={c.code}>{c.code} · {c.name}</option>)}
            </Select>
          </FormField>
          <FormField id="p_org" label="Organization" hint="Link a customer and a supplier record that are the same company.">
            <Combobox id="p_org" value={form.organization_id} onChange={(v) => set("organization_id", v)} placeholder="None"
              options={(orgs.data ?? []).map((o) => ({ value: o.id, label: o.legal_name }))} />
            <div className="flex gap-2">
              <Input aria-label="New organization name" placeholder="New organization…" value={newOrg} onChange={(e) => setNewOrg(e.target.value)} />
              <Button type="button" variant="outline" size="sm" className="h-9" disabled={!newOrg.trim()} loading={createOrg.isPending} onClick={() => createOrg.mutate()}>Add</Button>
            </div>
          </FormField>
          <FormField id="p_notes" label="Notes" className="sm:col-span-2"><Textarea id="p_notes" value={form.notes} onChange={(e) => set("notes", e.target.value)} /></FormField>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={save.isPending} disabled={!form.name.trim()}>{party ? "Save" : "Add"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
