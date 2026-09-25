const API_BASE = import.meta.env.VITE_API_URL || "/api";

export const getAuthToken = () => localStorage.getItem("yogii_token");
export const setAuthToken = (token) => localStorage.setItem("yogii_token", token);
export const clearAuthToken = () => localStorage.removeItem("yogii_token");

export async function apiRequest(endpoint, options = {}) {
  const token = getAuthToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {})
  };

  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  try {
    const response = await fetch(url, {
      ...options,
      headers
    });

    if (response.status === 401 && !endpoint.includes("/auth/")) {
      clearAuthToken();
      window.dispatchEvent(new Event("yogii_unauthorized"));
    }

    const data = await response.json().catch(() => null);

    if (!response.ok) {
      const errorMsg = data?.detail || (typeof data === "string" ? data : "Request failed");
      throw new Error(errorMsg);
    }

    return data;
  } catch (err) {
    throw err;
  }
}
