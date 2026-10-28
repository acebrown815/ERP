"use client";

import { Gantt } from "@/components/projects/gantt";
import { ProjectPickerPage } from "@/components/projects/project-picker-page";
import { Card, CardContent } from "@/components/ui/misc";

export default function TimelinePage() {
  return (
    <ProjectPickerPage
      title="Gantt timeline"
      description="Tasks, dependencies and milestones over time. Drag bars to reschedule."
      render={(projectId) => (
        <Card>
          <CardContent className="pt-6">
            <Gantt key={projectId} projectId={projectId} />
          </CardContent>
        </Card>
      )}
    />
  );
}
