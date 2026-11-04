"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, PlugZap } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/erp/form-field";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import type { BiddingSettings, ConnectionTest } from "@/lib/bidding";

type Form = { bids_webapp_url: string; bids_secret: string; jobs_webapp_url: string; jobs_token: string; jobs_tabs: string; cache_minutes: string };

const fromSettings = (s: BiddingSettings): Form => ({
  bids_webapp_url: s.bids_webapp_url,
  bids_secret: "",
  jobs_webapp_url: s.jobs_webapp_url,
  jobs_token: "",
  jobs_tabs: s.jobs_tabs.join("\n"),
  cache_minutes: String(Math.round(s.cache_seconds / 60)),
});

const tabsOf = (text: string) => text.split(/[\n,]/).map((t) => t.trim()).filter(Boolean);

function TestResult({ result }: { result: ConnectionTest | undefined }) {
  if (!result) return null;
  return (
    <div role="status" className="flex flex-col gap-1 text-sm">
      <p className="flex items-center gap-1.5">
        {result.ok ? <CircleCheck className="size-4 text-success" aria-hidden /> : <CircleX className="size-4 text-destructive" aria-hidden />}
        {result.message}
      </p>
      {result.tabs.length > 0 && <p className="text-xs text-muted-foreground">{result.tabs.map((t) => `${t.name} (${t.rows})`).join(" · ")}</p>}
    </div>
  );
}

/** Settings → Bidding Sheets: where the two Apps Script web apps are. Secrets are write-only. */
export function ConnectionSettings() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["bidding", "settings"], queryFn: () => api.get<BiddingSettings>("/bidding/settings") });
  const s = settings.data;
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [tests, setTests] = useState<{ bids?: ConnectionTest; jobs?: ConnectionTest }>({});

  useEffect(() => {
    if (s) setForm(fromSettings(s));
  }, [s]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<BiddingSettings>("/bidding/settings", body),
    onSuccess: (data) => {
      qc.setQueryData(["bidding", "settings"], data);
      qc.invalidateQueries({ queryKey: ["bidding"] });
      setErrors({});
      toast.success("Bidding sheets saved");
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        toast.error(err.status === 412 ? "Someone else changed these settings; reload the page" : err.message);
      } else toast.error("Could not save");
    },
  });
  const test = useMutation({
    mutationFn: (target: "bids" | "jobs") =>
      api.post<ConnectionTest>("/bidding/settings/test", {
        target,
        url: target === "bids" ? form?.bids_webapp_url : form?.jobs_webapp_url,
        secret: (target === "bids" ? form?.bids_secret : form?.jobs_token) || undefined,
        tabs: target === "jobs" && form ? tabsOf(form.jobs_tabs) : undefined,
      }),
    onSuccess: (result, target) => setTests((t) => ({ ...t, [target]: result })),
    onError: () => toast.error("Could not run the test"),
  });

  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => settings.refetch()} />;
  if (!s || !form) return <TableSkeleton rows={4} />;

  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });

  const submit = () => {
    const body: Record<string, unknown> = { version: s.version };
    if (form.bids_webapp_url.trim() !== s.bids_webapp_url) body.bids_webapp_url = form.bids_webapp_url.trim();
    if (form.jobs_webapp_url.trim() !== s.jobs_webapp_url) body.jobs_webapp_url = form.jobs_webapp_url.trim();
    if (form.bids_secret.trim()) body.bids_secret = form.bids_secret.trim();
    if (form.jobs_token.trim()) body.jobs_token = form.jobs_token.trim();
    const tabs = tabsOf(form.jobs_tabs);
    if (tabs.join("|") !== s.jobs_tabs.join("|")) body.jobs_tabs = tabs;
    const minutes = Number(form.cache_minutes);
    if (Number.isFinite(minutes) && minutes > 0 && Math.round(minutes * 60) !== s.cache_seconds) body.cache_seconds = Math.round(minutes * 60);
    save.mutate(body);
  };
  const removeSecret = (name: "bids_secret" | "jobs_token") => save.mutate({ version: s.version, [name]: "" });

  return (
    <form
      className="mb-6 grid gap-6 lg:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle>Bids sheet (BidExtension)</CardTitle>
          <CardDescription>
            The web app from <code>BidExtension/docs/sheets-sync/Code.gs</code>, deployed with the <code>listTabs</code> / <code>readTabs</code> actions.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <FormField id="bids_url" label="Web app URL" error={errors.bids_webapp_url}>
            <Input id="bids_url" value={form.bids_webapp_url} onChange={(e) => set({ bids_webapp_url: e.target.value })} placeholder="https://script.google.com/macros/s/…/exec" aria-invalid={!!errors.bids_webapp_url} />
          </FormField>
          <FormField
            id="bids_secret"
            label="Shared secret"
            error={errors.bids_secret}
            hint={s.bids_secret_set ? `Saved (${s.bids_secret_hint}). Leave blank to keep it; a new URL needs it entered again.` : "The SHARED_SECRET at the top of Code.gs"}
          >
            <div className="flex gap-2">
              <Input id="bids_secret" type="password" autoComplete="off" value={form.bids_secret} onChange={(e) => set({ bids_secret: e.target.value })} placeholder={s.bids_secret_set ? "••••••••" : ""} />
              {s.bids_secret_set && <Button type="button" variant="ghost" onClick={() => removeSecret("bids_secret")}>Remove</Button>}
            </div>
          </FormField>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" loading={test.isPending && test.variables === "bids"} onClick={() => test.mutate("bids")}>
              <PlugZap /> Test
            </Button>
            <TestResult result={tests.bids} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Job list (job-scraper)</CardTitle>
          <CardDescription>The web app from <code>job-scraper/apps_script/Code.gs</code> and its TOKEN script property.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <FormField id="jobs_url" label="Web app URL" error={errors.jobs_webapp_url}>
            <Input id="jobs_url" value={form.jobs_webapp_url} onChange={(e) => set({ jobs_webapp_url: e.target.value })} placeholder="https://script.google.com/macros/s/…/exec" aria-invalid={!!errors.jobs_webapp_url} />
          </FormField>
          <FormField
            id="jobs_token"
            label="Token"
            error={errors.jobs_token}
            hint={s.jobs_token_set ? `Saved (${s.jobs_token_hint}). Leave blank to keep it; a new URL needs it entered again.` : "The TOKEN script property of that web app"}
          >
            <div className="flex gap-2">
              <Input id="jobs_token" type="password" autoComplete="off" value={form.jobs_token} onChange={(e) => set({ jobs_token: e.target.value })} placeholder={s.jobs_token_set ? "••••••••" : ""} />
              {s.jobs_token_set && <Button type="button" variant="ghost" onClick={() => removeSecret("jobs_token")}>Remove</Button>}
            </div>
          </FormField>
          <FormField
            id="jobs_tabs"
            label="Tabs to read"
            hint="One per line, exactly as named in the sheet. A misspelled name makes that script create an empty tab."
          >
            <Textarea id="jobs_tabs" rows={4} value={form.jobs_tabs} onChange={(e) => set({ jobs_tabs: e.target.value })} />
          </FormField>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" loading={test.isPending && test.variables === "jobs"} onClick={() => test.mutate("jobs")}>
              <PlugZap /> Test
            </Button>
            <TestResult result={tests.jobs} />
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-end gap-4 lg:col-span-2">
        <FormField id="cache_minutes" label="Reuse data for (minutes)" error={errors.cache_seconds} hint="Pages read the sheets again after this, or on Refresh.">
          <Input id="cache_minutes" type="number" min={1} max={60} className="w-28" value={form.cache_minutes} onChange={(e) => set({ cache_minutes: e.target.value })} />
        </FormField>
        <Button type="submit" loading={save.isPending}>Save connections</Button>
      </div>
    </form>
  );
}
