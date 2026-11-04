"use client";

// Bidding analytics: types mirror apps/api/app/modules/bidding/schemas.py. They are written by hand so the
// pages type-check before `npm run gen:api`; after regenerating they can be swapped for the generated ones.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { SortingState } from "@tanstack/react-table";

import { api } from "@/lib/api";
import { useMe } from "@/lib/session";

export type JobStatus = "not_bid" | "applied";

/** A table's sorted column as query parameters. Column ids are the API's sort names. */
export const sortParams = (sorting: SortingState) => ({ sort: sorting[0]?.id, desc: sorting[0]?.desc || undefined });

export type SourceState = { configured: boolean; fetched_at: string | null; error: string | null };
export type DataState = { built_at: string; bids: SourceState; jobs: SourceState; job_list_from: string | null };

export type Bid = {
  tab: string;
  employee_id: string | null;
  employee_name: string | null;
  row: number;
  date: string | null;
  title: string;
  link: string;
  company: string;
  location: string;
  salary: string;
  resume: string;
  score: number | null;
  duplicate: boolean;
  in_job_list: boolean;
  job_key: string | null;
  region: string | null;
  role: string | null;
  listings: string[];
};
export type BidsPage = { items: Bid[]; total: number; page: number; page_size: number; data: DataState };

export type JobBid = { tab: string; employee_id: string | null; employee_name: string | null; date: string | null; score: number | null };
export type Job = {
  key: string;
  region: string;
  role: string;
  listings: string[];
  title: string;
  company: string;
  location: string;
  country: string;
  remote: boolean;
  skill_level: string;
  salary: string;
  ats: string;
  is_recruiter: boolean;
  posted_at: string | null;
  first_seen: string | null;
  url: string;
  status: JobStatus;
  duplicate: boolean;
  bids: JobBid[];
};
export type Facets = { regions: string[]; roles: string[]; ats: string[]; skill_levels: string[] };
export type JobsPage = {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
  not_bid: number;
  applied: number;
  facets: Facets;
  data: DataState;
};

export type DayPoint = { date: string; applied: number; scraped: number; avg_score: number | null };
export type Count = { name: string; count: number };
export type EmployeeRow = {
  employee_id: string | null;
  name: string;
  /** The employee's profile names, or the one unclaimed tab. */
  tabs: string[];
  applied: number;
  avg_score: number | null;
  min_score: number | null;
  max_score: number | null;
  days_active: number;
  last_date: string | null;
  resumes: Count[];
  by_day: number[];
};
export type Stats = {
  date_from: string;
  date_to: string;
  employee_id: string | null;
  employee_name: string | null;
  profile_names: string[];
  profile_missing: boolean;
  applied: number;
  avg_score: number | null;
  active_bidders: number;
  scraped: number;
  scraped_bid: number;
  coverage_pct: number | null;
  outside_job_list: number;
  duplicates: number;
  series: DayPoint[];
  score_buckets: Count[];
  resumes: Count[];
  companies: Count[];
  roles: Count[];
  profiles: Count[];
  employees: EmployeeRow[];
  data: DataState;
};

export type DailyRow = {
  employee_id: string | null;
  name: string;
  tabs: string[];
  applied: number;
  avg_score: number | null;
  min_score: number | null;
  max_score: number | null;
  resumes: Count[];
  in_job_list: number;
};
export type Daily = { date_from: string; date_to: string; applied: number; avg_score: number | null; active_bidders: number; scraped: number; rows: DailyRow[]; data: DataState };

export type ProfileTab = { name: string; found: boolean; rows: number; applied: number };
export type Profile = {
  employee_id: string;
  employee_name: string;
  profile_names: string[];
  tabs: ProfileTab[];
  rows: number;
  applied: number;
  available_tabs: string[];
  data: DataState;
};

export type Person = { employee_id: string; name: string; profile_names: string[] };
export type Sources = {
  data: DataState;
  tabs: { name: string; rows: number; applied: number; last_date: string | null; employee_id: string | null; employee_name: string | null }[];
  unclaimed_tabs: string[];
  employees: Person[];
  profiles_without_tab: Person[];
  job_tabs: { name: string; rows: number }[];
  cache_seconds: number;
};

export type Range = { from: string; to: string };

/** Everyone's numbers (bidding.read with "all" scope), or only your own. */
export function useSeesAllBids(): boolean {
  return useMe().permissions["bidding.read"] === "all";
}

/** Local calendar date as YYYY-MM-DD. */
export function isoDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function lastDays(n: number): Range {
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - (n - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

export function useStats(range: Range, employeeId?: string | null, tab?: string | null) {
  return useQuery({
    queryKey: ["bidding", "stats", range, employeeId ?? null, tab ?? null],
    queryFn: () => api.get<Stats>("/bidding/stats", { date_from: range.from, date_to: range.to, employee_id: employeeId, tab }),
    placeholderData: keepPreviousData,
  });
}

/** Pull both sheets again and reload every bidding query. */
export function useRefreshSheets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<DataState>("/bidding/refresh"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bidding"] }),
  });
}

export function useProfile() {
  return useQuery({ queryKey: ["bidding", "profile"], queryFn: () => api.get<Profile>("/bidding/me/profile"), retry: false });
}

export type BiddingSettings = {
  bids_webapp_url: string;
  bids_secret_set: boolean;
  bids_secret_hint: string | null;
  jobs_webapp_url: string;
  jobs_token_set: boolean;
  jobs_token_hint: string | null;
  jobs_tabs: string[];
  cache_seconds: number;
  version: number;
};
export type ConnectionTest = { ok: boolean; message: string; tabs: { name: string; rows: number }[] };
