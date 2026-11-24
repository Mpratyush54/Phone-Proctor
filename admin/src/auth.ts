import { createContext, useContext } from "react";

export type Staff = { user_id: string; org_id: string; roles: string[]; permissions: string[]; csrf: string };
export const StaffContext = createContext<Staff | null>(null);
export function usePermissions() {
  const staff = useContext(StaffContext);
  return (permission: string) => !!(staff?.permissions.includes(permission) || staff?.permissions.includes("platform.ops"));
}
