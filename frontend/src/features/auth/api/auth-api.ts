import { apiClient } from "@/lib/api-client";
import type { LoginRequest, LoginResponse, UserResponse } from "../types";

export const login = async (payload: LoginRequest): Promise<LoginResponse> => {
  const { data } = await apiClient.post<LoginResponse>("/auth/login", payload);
  return data;
};

export const getCurrentUser = async (): Promise<UserResponse> => {
  const { data } = await apiClient.get<UserResponse>("/auth/me");
  return data;
};
