"use client";

import { useEffect, useState, type ReactNode } from "react";

import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { Card } from "@/components/ui/misc";

import { ProjectSelect, useProjectList } from "./shared";

const KEY = "erp.lastProject";

/** A page that shows one project's view (board, timeline) with a project picker; remembers the last pick. */
export function ProjectPickerPage({ title, description, render }: { title: string; description: string; render: (projectId: string) => ReactNode }) {
  const projects = useProjectList();
  const [projectId, setProjectId] = useState<string | null>(null);
  useEffect(() => {
    if (projectId || !projects.data?.length) return;
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(KEY);
    } catch {
      saved = null;
    }
    const pick = projects.data.find((p) => p.id === saved) ?? projects.data.find((p) => p.status === "active") ?? projects.data[0];
    setProjectId(pick?.id ?? null);
  }, [projects.data, projectId]);
  const choose = (id: string) => {
    setProjectId(id);
    try {
      localStorage.setItem(KEY, id);
    } catch {
      // Remembering the project is a convenience only.
    }
  };
  return (
    <>
      <PageHeader title={title} description={description} actions={<ProjectSelect value={projectId} onChange={choose} />} />
      {projects.data && projects.data.length === 0 ? <Card><EmptyState title="No projects yet" /></Card> : projectId ? render(projectId) : null}
    </>
  );
}
