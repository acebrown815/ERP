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

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
