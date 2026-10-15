import { apiClient } from "@/lib/api-client";

export type ChangePasswordRequest = {
  current_password: string;
  new_password: string;
};

export const changeOwnPassword = async (payload: ChangePasswordRequest): Promise<void> => {
  await apiClient.post("/me/password", payload);
};
