import axios, { isAxiosError, type InternalAxiosRequestConfig } from "axios";
import qs from "qs";

const API_URL = import.meta.env.VITE_BACKEND_API_URL;

export const apiClient = axios.create({
  baseURL: API_URL,
  headers: {
    "Content-Type": "application/json",
  },
  paramsSerializer: (params) => qs.stringify(params, { arrayFormat: "repeat" }),
});

/**
 * The token getter is synchronous because the API has no refresh flow: there is
 * nothing to await before a request goes out.
 */
export const setupApiClientInterceptor = (
  getToken: () => string | null,
  onUnauthorized: () => void,
) => {
  // Remove existing interceptors to avoid duplicates
  apiClient.interceptors.request.clear();
  apiClient.interceptors.response.clear();

  apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = getToken();

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    return config;
  });

  apiClient.interceptors.response.use(
    (response) => response,
    (error: unknown) => {
      if (isAxiosError(error) && error.response?.status === 401) {
        onUnauthorized();
      }
      return Promise.reject(error);
    },
  );
};
