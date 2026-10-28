// Friendly aliases over the generated OpenAPI types (`npm run gen:api` regenerates src/types/api.ts).
import type { components } from "@/types/api";

type S = components["schemas"];

export type Me = S["MeOut"];
export type User = S["UserOut"];
export type RoleRef = S["RoleRef"];
export type Role = S["RoleOut"];
export type Permission = S["PermissionOut"];
export type Company = S["CompanyOut"];
export type Currency = S["CurrencyOut"];
export type ExchangeRate = S["RateOut"];
export type Category = S["CategoryOut"];
export type CategoryGroup = S["GroupOut"];
export type AuditEntry = S["AuditLogOut"];
export type Attachment = S["AttachmentOut"];

export type Account = S["AccountOut"];
export type Period = S["PeriodOut"];
export type JournalEntry = S["JournalOut"];
export type JournalLine = S["LineOut"];
export type JournalPreview = S["JournalPreviewOut"];
export type TrialBalance = S["TrialBalanceOut"];
export type ProfitLoss = S["ProfitLossOut"];
export type BalanceSheet = S["BalanceSheetOut"];
export type StatementRow = S["StatementRow"];
export type Ledger = S["LedgerOut"];

export type Party = S["PartyOut"];
export type Organization = S["OrganizationOut"];
export type Employee = S["EmployeeOut"];
export type Department = S["DepartmentOut"];
export type Project = S["ProjectOut"];
export type ProjectMember = S["MemberOut"];

export type PaymentAccount = S["PaymentAccountOut"];
export type PaymentEntry = S["EntryOut"];
export type PaymentPreview = S["PaymentPreviewOut"];
export type Allocation = S["AllocationOut"];
export type SplitRow = S["SplitRow-Input"];

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
