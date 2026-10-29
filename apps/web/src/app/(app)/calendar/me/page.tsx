"use client";

import { PageHeader } from "@/components/erp/page-header";
import { CalendarView } from "@/components/calendar/calendar-view";
import { Card, CardContent } from "@/components/ui/misc";

export default function MyCalendarPage() {
  return (
    <>
      <PageHeader
        title="My calendar"
        description="Your meetings and leave, your team's and projects' events, company events, plus your tasks and project milestones and deadlines."
      />
      <Card>
        <CardContent className="pt-6">
          <CalendarView view="me" />
        </CardContent>
      </Card>
    </>
  );
}
