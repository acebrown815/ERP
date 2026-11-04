/**
 * Whose bidding numbers the dashboard shows. Someone who bids sees their own, even if a role such as Project Manager
 * lets them see everyone's: those stay on Team Overview. Only a manager with no profile names gets the team view.
 */
export function dashboardScope(
  profile: { employee_id: string; profile_names: string[] } | undefined,
  seesAll: boolean,
): { team: boolean; employeeId?: string } {
  if (profile?.profile_names.length) return { team: false, employeeId: profile.employee_id };
  return { team: seesAll };
}
