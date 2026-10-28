"use client";

import { KanbanBoard } from "@/components/projects/kanban";
import { ProjectPickerPage } from "@/components/projects/project-picker-page";

export default function BoardPage() {
  return (
    <ProjectPickerPage
      title="Kanban board"
      description="Drag tasks between columns to change their status or order."
      render={(projectId) => <KanbanBoard key={projectId} projectId={projectId} />}
    />
  );
}
