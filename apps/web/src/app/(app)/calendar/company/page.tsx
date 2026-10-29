"use client";

import { PageHeader } from "@/components/erp/page-header";
import { CalendarView } from "@/components/calendar/calendar-view";
import { Card, CardContent } from "@/components/ui/misc";

export default function CompanyCalendarPage() {
  return (
    <>
      <PageHeader
        title="Company calendar"
        description="Company events, who is on (approved) leave, and project milestones and deadlines."
      />
      <Card>
        <CardContent className="pt-6">
          <CalendarView view="company" defaults={{ scope: "company" }} />
        </CardContent>
      </Card>
    </>
  );
}
