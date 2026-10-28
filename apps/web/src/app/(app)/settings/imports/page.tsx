"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileUp } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/erp/page-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";

type Entity = "parties" | "employees" | "projects";
type Result = { entity: string; dry_run: boolean; total: number; created: number; committed: boolean; errors: { row: number; column: string; message: string }[] };

const HELP: Record<Entity, { title: string; body: string }> = {
  parties: { title: "Customers, suppliers and other parties", body: "kind must be customer, supplier or other. Duplicates by name are rejected." },
  employees: { title: "Employees", body: "start_date as YYYY-MM-DD. employment_type by name or key (full_time, contractor…). Missing departments are created." },
  projects: { title: "Projects", body: "customer by name or CUS- number, manager by employee email, project_type by name or key. Import customers and employees first." },
};

export default function ImportsPage() {
  const qc = useQueryClient();
  const [entity, setEntity] = useState<Entity>("parties");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.set("file", file);
      form.set("dry_run", String(dryRun));
      const r = await api.post<Result>(`/imports/${entity}`, form);
      setResult(r);
      if (r.committed) {
        toast.success(`Imported ${r.created} ${entity}`);
        qc.invalidateQueries();
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? [err.message, ...err.errors.map((e) => e.message)].join(" · ") : "Import failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Data import" description="Bring in existing records from a spreadsheet saved as CSV (UTF-8). Check first with a dry run; a real import is all-or-nothing." />
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>1. Choose what to import</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Select aria-label="What to import" value={entity} onChange={(e) => { setEntity(e.target.value as Entity); setResult(null); }}>
              <option value="parties">Parties</option>
              <option value="employees">Employees</option>
              <option value="projects">Projects</option>
            </Select>
            <div className="text-sm">
              <p className="font-medium">{HELP[entity].title}</p>
              <p className="text-muted-foreground">{HELP[entity].body}</p>
            </div>
            <Button variant="outline" asChild>
              <a href={`/api/v1/imports/${entity}/template`}><Download /> Download template</a>
            </Button>
            <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" aria-label="CSV file"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }} />
            <Button variant="outline" onClick={() => input.current?.click()}><FileUp /> {file ? file.name : "Choose CSV file"}</Button>
            <div className="flex gap-2">
              <Button className="flex-1" variant="outline" disabled={!file} loading={busy} onClick={() => void run(true)}>Dry run</Button>
              <Button className="flex-1" disabled={!file || !result || result.errors.length > 0 || !result.dry_run} loading={busy} onClick={() => void run(false)}>Import</Button>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>2. Review</CardTitle>
            <CardDescription>{result ? (result.dry_run ? "Dry run: nothing was saved." : result.committed ? "Imported." : "Nothing was saved.") : "Run a dry run to check every row."}</CardDescription>
          </CardHeader>
          <CardContent>
            {result && (
              <div className="flex flex-col gap-4">
                <div className="flex gap-6 text-sm">
                  <span>Rows: <strong>{result.total}</strong></span>
                  <span>{result.dry_run ? "Would import" : "Imported"}: <strong>{result.committed || result.dry_run ? result.created : 0}</strong></span>
                  <span>Problems: <strong className={result.errors.length ? "text-destructive" : ""}>{result.errors.length}</strong></span>
                </div>
                {result.errors.length === 0 ? (
                  <p className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="size-4" /> {result.dry_run ? "Everything looks good. Click Import." : "Done."}</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                      <tr><th className="py-1.5 text-left font-medium">Row</th><th className="py-1.5 text-left font-medium">Column</th><th className="py-1.5 text-left font-medium">Problem</th></tr>
                    </thead>
                    <tbody>
                      {result.errors.map((e, i) => (
                        <tr key={i} className="border-b last:border-0"><td className="py-1.5 tabular">{e.row}</td><td className="py-1.5 font-mono text-xs">{e.column}</td><td className="py-1.5">{e.message}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
