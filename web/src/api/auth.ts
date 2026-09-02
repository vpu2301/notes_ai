import { api } from "./http";
import type { LoginResponse, MeResponse } from "./types";

export function login(email: string, password: string, otp?: string): Promise<LoginResponse> {
  return api<LoginResponse>("auth", "/auth/login", {
    method: "POST",
    json: otp ? { email, password, otp } : { email, password },
    auth: false,
    credentials: true, // receive the HttpOnly refresh cookie
  });
}

export function logout(): Promise<void> {
  return api<void>("auth", "/auth/logout", {
    method: "POST",
    credentials: true,
  });
}

export function fetchMe(): Promise<MeResponse> {
  return api<MeResponse>("auth", "/auth/me");
}
