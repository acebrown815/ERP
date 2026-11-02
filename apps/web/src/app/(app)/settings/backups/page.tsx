"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, DatabaseBackup, Download, Loader2, RotateCcw, Trash2, Upload, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge, Card, CardContent } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import type { Backup, BackupJob, Backups } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const KIND: Record<Backup["kind"], { label: string; variant: "default" | "muted" | "outline" | "warning" }> = {
  auto: { label: "Nightly", variant: "muted" },
  manual: { label: "Manual", variant: "default" },
  upload: { label: "Uploaded", variant: "outline" },
  "pre-restore": { label: "Before restore", variant: "warning" },
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? [err.message, ...err.errors.map((e) => e.message)].filter((m, i, a) => a.indexOf(m) === i).join(" · ") : fallback;
}

export default function BackupsPage() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [restoring, setRestoring] = useState<Backup | null>(null);
  const [deleting, setDeleting] = useState<Backup | null>(null);

  const q = useQuery({
    queryKey: ["backups"],
    queryFn: () => api.get<Backups>("/backups"),
    refetchInterval: (query) => (query.state.data?.job?.state === "running" ? 1500 : false),
  });
  const running = q.data?.job?.state === "running";

  const create = useMutation({
    mutationFn: () => api.post<BackupJob>("/backups"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backups"] }),
    onError: (err) => toast.error(errorText(err, "Could not start the backup")),
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.set("file", file);
      return api.post<Backup>("/backups/upload", form);
    },
    onSuccess: (b) => {
      toast.success(`Uploaded backup from ${formatDateTime(b.created_at)}`);
      qc.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: (err) => toast.error(errorText(err, "Upload failed")),
    onSettled: () => {
      if (input.current) input.current.value = "";
    },
  });

  return (
    <>
      <PageHeader
        title="Backups"
        description={`Copies of all company data. A backup is made automatically every night and kept ${q.data?.keep_days ?? 14} days; manual, uploaded and before-restore backups are kept until you delete them.`}
        actions={
          <>
            <input ref={input} type="file" accept=".zip,application/zip" className="sr-only" aria-label="Backup file"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); }} />
            <Button variant="outline" loading={upload.isPending} disabled={running} onClick={() => input.current?.click()}><Upload /> Upload backup</Button>
            <Button loading={create.isPending} disabled={running} onClick={() => create.mutate()}><DatabaseBackup /> Back up now</Button>
          </>
        }
      />
      {q.data?.job && <JobBanner job={q.data.job} />}
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data ? <TableSkeleton rows={4} /> : q.data.items.length === 0 ? (
        <EmptyState title="No backups yet" description="Click Back up now, or upload a backup file made by another installation." />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <THead>
                <TR>
                  <TH>Created</TH>
                  <TH>Type</TH>
                  <TH className="text-right">Records</TH>
                  <TH className="text-right">Files</TH>
                  <TH className="text-right">Size</TH>
                  <TH>Version</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {q.data.items.map((b) => (
                  <TR key={b.name}>
                    <TD className="whitespace-nowrap" title={b.name}>{formatDateTime(b.created_at)}</TD>
                    <TD><Badge variant={KIND[b.kind].variant}>{KIND[b.kind].label}</Badge></TD>
                    <TD className="text-right tabular">{b.rows.toLocaleString()}</TD>
                    <TD className="text-right tabular">{b.files.toLocaleString()}</TD>
                    <TD className="text-right tabular whitespace-nowrap">{formatSize(b.size)}</TD>
                    <TD className="font-mono text-xs">{b.schema_version}</TD>
                    <TD>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" asChild>
                          <a href={`/api/v1/backups/${encodeURIComponent(b.name)}/download`} download><Download /> Download</a>
                        </Button>
                        <Button variant="ghost" size="sm" disabled={running} onClick={() => setRestoring(b)}><RotateCcw /> Restore</Button>
                        <Button variant="ghost" size="sm" disabled={running} aria-label={`Delete backup from ${formatDateTime(b.created_at)}`} onClick={() => setDeleting(b)}><Trash2 /></Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        Keep copies somewhere other than this server: download a backup now and then. Only upload backup files you made yourself; restoring one replaces every record in the system.
      </p>

      <RestoreDialog backup={restoring} onOpenChange={(o) => !o && setRestoring(null)} onStarted={() => qc.invalidateQueries({ queryKey: ["backups"] })} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete backup?"
        description={deleting ? `The backup from ${formatDateTime(deleting.created_at)} will be deleted from the server. This cannot be undone.` : ""}
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await api.delete(`/backups/${encodeURIComponent(deleting.name)}`);
            toast.success("Backup deleted");
            qc.invalidateQueries({ queryKey: ["backups"] });
          } catch (err) {
            toast.error(errorText(err, "Could not delete the backup"));
            throw err;
          }
        }}
      />
    </>
  );
}

function JobBanner({ job }: { job: BackupJob }) {
  const what = job.kind === "restore" ? "Restore" : "Backup";
  const icon =
    job.state === "running" ? <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
    : job.state === "succeeded" ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
    : <XCircle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />;
  const title =
    job.state === "running" ? (job.kind === "restore" ? "Restoring… everyone will be signed out when it finishes." : "Backing up…")
    : job.state === "succeeded" ? `${what} finished` : `${what} failed`;
  return (
    <Card className="mb-4" role="status">
      <CardContent className="flex items-start gap-3 py-4">
        {icon}
        <div className="text-sm">
          <p className="font-medium">{title}</p>
          {job.message && <p className="text-muted-foreground">{job.message}</p>}
          <p className="text-xs text-muted-foreground">
            Started {formatDateTime(job.started_at)}{job.by ? ` by ${job.by}` : ""}{job.finished_at ? ` · finished ${formatDateTime(job.finished_at)}` : ""}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function RestoreDialog({ backup, onOpenChange, onStarted }: { backup: Backup | null; onOpenChange: (o: boolean) => void; onStarted: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  const close = (open: boolean) => {
    if (!open) {
      setPassword("");
      setError(undefined);
    }
    onOpenChange(open);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!backup) return;
    setBusy(true);
    setError(undefined);
    try {
      await api.post<BackupJob>(`/backups/${encodeURIComponent(backup.name)}/restore`, { password });
      toast.success("Restore started. You will be signed out when it finishes.");
      onStarted();
      close(false);
    } catch (err) {
      if (err instanceof ApiError && err.fieldErrors().password) setError(err.fieldErrors().password);
      else toast.error(errorText(err, "Could not start the restore"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={!!backup} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Restore this backup?</DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-col gap-2">
              <p>
                Every record in the system will be replaced with the backup from{" "}
                <strong>{backup ? formatDateTime(backup.created_at) : ""}</strong>. Anything entered after that is lost.
              </p>
              <p>The current data is saved as a &ldquo;Before restore&rdquo; backup first. The system is unavailable for a few seconds and everyone is signed out.</p>
            </div>
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <FormField id="restore_password" label="Your password" error={error}>
            <Input id="restore_password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => close(false)}>Cancel</Button>
            <Button type="submit" variant="destructive" loading={busy} disabled={!password}>Replace all data</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
