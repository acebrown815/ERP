"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, MoreHorizontal, Plus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { AccountPicker } from "@/components/erp/pickers";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { formatAmount, formatShort, sign } from "@/lib/money";
import { currencyPrecision, useAccounts, useCompany, useCurrencies } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { Account } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROOT_LABEL: Record<string, string> = { asset: "Asset", liability: "Liability", equity: "Equity", income: "Income", expense: "Expense" };

function AccountDialog({ account, parentId, accounts, onClose }: { account: Account | null; parentId: string | null; accounts: Account[]; onClose: () => void }) {
  const qc = useQueryClient();
  const currencies = useCurrencies();
  const company = useCompany();
  const types = useQuery({ queryKey: ["account-types"], queryFn: () => api.get<Record<string, string[]>>("/accounts/types"), staleTime: Infinity });
  const [form, setForm] = useState({
    code: account?.code ?? "",
    name: account?.name ?? "",
    parent_id: account?.parent_id ?? parentId,
    account_type: account?.account_type ?? "",
    is_group: account?.is_group ?? false,
    currency: account?.currency ?? "",
    description: account?.description ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const parent = accounts.find((a) => a.id === form.parent_id);
  const root = account?.root_type ?? parent?.root_type;
  const typeOptions = root ? types.data?.[root] ?? [] : [];

  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, account_type: form.account_type || null, currency: form.currency || null, description: form.description || null };
      return account
        ? api.patch<Account>(`/accounts/${account.id}`, { ...body, version: account.version })
        : api.post<Account>("/accounts", body);
    },
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      toast.success(account ? "Account updated" : `Account ${a.code} added`);
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
          <DialogTitle>{account ? `Edit ${account.code} ${account.name}` : "New account"}</DialogTitle>
          {account?.has_postings && <DialogDescription>This account has postings: its type, currency and group setting are locked.</DialogDescription>}
        </DialogHeader>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <FormField id="acc_code" label="Code" required error={errors.code}>
            <Input id="acc_code" value={form.code} className="font-mono" onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </FormField>
          <FormField id="acc_name" label="Name" required error={errors.name}>
            <Input id="acc_name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </FormField>
          <FormField id="acc_parent" label="Parent group" required error={errors.parent_id} className="sm:col-span-2">
            <AccountPicker id="acc_parent" value={form.parent_id} groupsOnly roots={account ? [account.root_type] : undefined}
              onChange={(v) => setForm({ ...form, parent_id: v })} clearable={false} />
          </FormField>
          {root && <p className="-mt-2 text-xs text-muted-foreground sm:col-span-2">Root type: {ROOT_LABEL[root]}</p>}
          <FormField id="acc_type" label="Type" error={errors.account_type}>
            <Select id="acc_type" value={form.account_type} disabled={account?.has_postings} onChange={(e) => setForm({ ...form, account_type: e.target.value })}>
              <option value="">Default</option>
              {typeOptions.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
            </Select>
          </FormField>
          <FormField id="acc_currency" label="Currency" error={errors.currency} hint={`Default: ${company.data?.base_currency ?? "base"}`}>
            <Select id="acc_currency" value={form.currency} disabled={account?.has_postings} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
              <option value="">Base currency</option>
              {currencies.data?.map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
            </Select>
          </FormField>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <Checkbox checked={form.is_group} disabled={account?.has_postings} onChange={(e) => setForm({ ...form, is_group: e.target.checked })} />
            Group (holds sub-accounts, can&apos;t receive postings)
          </label>
          <FormField id="acc_desc" label="Description" className="sm:col-span-2">
            <Textarea id="acc_desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </FormField>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={save.isPending}>{account ? "Save" : "Add account"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function ChartOfAccountsPage() {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can("accounts.manage");
  const canSeePayments = can("payments.create") || can("reports.financial");
  const accounts = useAccounts();
  const company = useCompany();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [showInactive, setShowInactive] = useState(false);
  const [currencyFilter, setCurrencyFilter] = useState("");
  const currencies = useCurrencies();
  const [dialog, setDialog] = useState<{ account: Account | null; parentId: string | null } | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);
  const base = company.data?.base_currency ?? "USD";

  // Currencies in use, for the filter (base first).
  const usedCurrencies = useMemo(() => {
    const set = new Set((accounts.data ?? []).filter((a) => !a.is_group).map((a) => a.currency));
    return [...set].sort((x, y) => (x === base ? -1 : y === base ? 1 : x.localeCompare(y)));
  }, [accounts.data, base]);

  const visible = useMemo(() => {
    const rows = accounts.data ?? [];
    // With a currency chosen: its accounts plus the groups above them.
    let keep: Set<string> | null = null;
    if (currencyFilter) {
      const byId = new Map(rows.map((a) => [a.id, a]));
      keep = new Set();
      for (const a of rows) {
        if (a.is_group || a.currency !== currencyFilter) continue;
        for (let cur: Account | undefined = a; cur && !keep.has(cur.id); cur = cur.parent_id ? byId.get(cur.parent_id) : undefined) keep.add(cur.id);
      }
    }
    const hidden = new Set<string>();
    return rows.filter((a) => {
      if (keep && !keep.has(a.id)) return false;
      if (a.parent_id && (hidden.has(a.parent_id) || collapsed.has(a.parent_id))) {
        hidden.add(a.id);
        return false;
      }
      return showInactive || a.is_active;
    });
  }, [accounts.data, collapsed, showInactive, currencyFilter]);

  const toggleActive = useMutation({
    mutationFn: (a: Account) => api.post<Account>(`/accounts/${a.id}/${a.is_active ? "deactivate" : "activate"}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not update"),
  });

  if (accounts.isError) return <ErrorState error={accounts.error} onRetry={() => accounts.refetch()} />;

  return (
    <>
      <PageHeader
        title="Chart of accounts"
        description={`From posted ledger entries. Accounts in another currency (e.g. a USDT wallet) also show their balance in that currency and its value at the latest saved rate; "Recorded" is the ${base} value the books hold. Groups total their sub-accounts.`}
        actions={manage && <Button onClick={() => setDialog({ account: null, parentId: null })}><Plus /> New account</Button>}
      />
      <Card>
        <div className="flex items-center justify-between gap-3 border-b px-4 py-2">
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => setCollapsed(new Set())}>Expand all</Button>
            <Button variant="ghost" size="sm" onClick={() => setCollapsed(new Set((accounts.data ?? []).filter((a) => a.is_group && a.depth === 0).map((a) => a.id)))}>
              Collapse all
            </Button>
          </div>
          <div className="flex items-center gap-4">
            <Select aria-label="Currency" className="h-8 w-auto" value={currencyFilter} onChange={(e) => setCurrencyFilter(e.target.value)}>
              <option value="">All currencies</option>
              {usedCurrencies.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Checkbox checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Show inactive
            </label>
          </div>
        </div>
        {accounts.isLoading ? <TableSkeleton rows={12} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="h-10 px-3 text-left font-medium">Account</th>
                  <th className="hidden h-10 px-3 text-left font-medium md:table-cell">Type</th>
                  <th className="h-10 px-3 text-right font-medium">In own currency</th>
                  <th className="h-10 px-3 text-right font-medium">At today&apos;s rate ({base})</th>
                  <th className="h-10 px-3 text-right font-medium">Recorded ({base})</th>
                  <th className="w-12" />
                </tr>
              </thead>
              <tbody>
                {visible.map((a) => {
                  const isCollapsed = collapsed.has(a.id);
                  return (
                    <tr key={a.id} className={cn("border-b last:border-0 hover:bg-muted/40", !a.is_active && "opacity-50", a.is_group && "font-medium")}>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1" style={{ paddingLeft: a.depth * 18 }}>
                          {a.is_group ? (
                            <button type="button" aria-label={isCollapsed ? "Expand" : "Collapse"} className="text-muted-foreground"
                              onClick={() => setCollapsed((s) => { const n = new Set(s); if (n.has(a.id)) n.delete(a.id); else n.add(a.id); return n; })}>
                              {isCollapsed ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
                            </button>
                          ) : <span className="w-4" />}
                          {canSeePayments ? (
                            <Link
                              href={`/accounting/payment-entries?account_ids=${a.id}`}
                              className="flex items-center gap-1 hover:underline"
                              title={a.is_group ? "Show payments booked to this group's accounts" : "Show payments booked to this account"}
                            >
                              <span className="font-mono text-xs text-muted-foreground">{a.code}</span>
                              <span>{a.name}</span>
                            </Link>
                          ) : (
                            <>
                              <span className="font-mono text-xs text-muted-foreground">{a.code}</span>
                              <span>{a.name}</span>
                            </>
                          )}
                          {a.currency !== base && <Badge variant="outline">{a.currency}</Badge>}
                          {!a.is_active && <Badge variant="muted">Inactive</Badge>}
                        </div>
                      </td>
                      <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">{a.is_group ? "Group" : a.account_type.replace("_", " ")}</td>
                      <td className="tabular px-3 py-2 text-right">
                        {a.balance_in_currency != null ? (
                          <span className={cn(sign(a.balance_in_currency) < 0 && "text-destructive")}>
                            {formatShort(a.balance_in_currency, currencyPrecision(currencies.data, a.currency))} {a.currency}
                          </span>
                        ) : ""}
                      </td>
                      <td className="tabular px-3 py-2 text-right">
                        {a.value_at_rate != null ? (
                          <span title={a.rate ? `Rate ${formatAmount(a.rate, 4)}` : undefined} className={cn(sign(a.value_at_rate) < 0 && "text-destructive")}>
                            {formatAmount(a.value_at_rate)}
                          </span>
                        ) : a.balance_in_currency != null ? (
                          <span className="text-xs text-warning">no saved rate</span>
                        ) : sign(a.balance) || a.has_postings ? (
                          <span className={cn(sign(a.balance) < 0 && "text-destructive")}>{formatAmount(a.balance)}</span>
                        ) : ""}
                      </td>
                      <td className={cn("tabular px-3 py-2 text-right text-muted-foreground", sign(a.balance) < 0 && "text-destructive")}>
                        {sign(a.balance) || a.has_postings ? formatAmount(a.balance) : ""}
                      </td>
                      <td className="px-1 py-1 text-right">
                        {manage && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" aria-label={`Actions for ${a.name}`}><MoreHorizontal /></Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent>
                              <DropdownMenuItem onSelect={() => setDialog({ account: a, parentId: a.parent_id ?? null })}>Edit</DropdownMenuItem>
                              {a.is_group && <DropdownMenuItem onSelect={() => setDialog({ account: null, parentId: a.id })}>Add sub-account</DropdownMenuItem>}
                              {!a.system_key && (
                                <>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem onSelect={() => toggleActive.mutate(a)}>{a.is_active ? "Deactivate" : "Activate"}</DropdownMenuItem>
                                  {!a.has_postings && <DropdownMenuItem destructive onSelect={() => setDeleting(a)}>Delete</DropdownMenuItem>}
                                </>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {dialog && <AccountDialog {...dialog} accounts={accounts.data ?? []} onClose={() => setDialog(null)} />}
      {deleting && (
        <ConfirmDialog open onOpenChange={(o) => !o && setDeleting(null)} title={`Delete ${deleting.code} ${deleting.name}?`}
          description="Only accounts that were never used can be deleted." confirmLabel="Delete" destructive
          onConfirm={async () => {
            try {
              await api.delete(`/accounts/${deleting.id}`);
              qc.invalidateQueries({ queryKey: ["accounts"] });
              toast.success("Account deleted");
            } catch (err) {
              toast.error(err instanceof ApiError ? err.message : "Could not delete");
              throw err;
            }
          }} />
      )}
    </>
  );
}
