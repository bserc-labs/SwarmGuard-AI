/**
 * Authentication state.
 *
 * The previous implementation read token and role directly from module scope on
 * every render, so those values did not participate in React state and could go
 * stale. They are now held in state and updated through the same code paths that
 * write storage.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getRole,
  getToken,
  isAuthenticated,
  login as performLogin,
  logout as clearStoredSession,
} from "@/services/auth";
import { api, ApiError, type UserInfo } from "@/services/api";

interface AuthContextValue {
  user: UserInfo | null;
  token: string | null;
  /** Role from the login response. Prefer `user.role` once loaded. */
  role: string | null;
  isLoggedIn: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const [user, setUser] = useState<UserInfo | null>(null);
  const [token, setToken] = useState<string | null>(() => getToken());
  const [role, setRole] = useState<string | null>(() => getRole());
  const [isLoading, setIsLoading] = useState<boolean>(() => isAuthenticated());

  // Resolve the stored token into a user on first mount. isLoading is seeded
  // from isAuthenticated() at initialisation, so the no-token case needs no
  // synchronous state write here.
  useEffect(() => {
    if (!isAuthenticated()) return;

    let cancelled = false;

    api
      .getMe()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setRole(me.role);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // A 401 already cleared storage inside the client. Any other failure
        // (network, 500) should not sign the operator out — keep the session and
        // let the individual views report their own errors.
        if (error instanceof ApiError && error.status === 401) {
          clearStoredSession();
          setUser(null);
          setToken(null);
          setRole(null);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const response = await performLogin(username, password);
    setToken(response.access_token);
    setRole(response.role);

    // Fetch the profile so role checks use the authoritative server value.
    const me = await api.getMe();
    setUser(me);
    setRole(me.role);
  }, []);

  const logout = useCallback(() => {
    clearStoredSession();
    setUser(null);
    setToken(null);
    setRole(null);
    // Drop cached tenant data so the next sign-in cannot briefly show it.
    queryClient.clear();
    // A full navigation rather than a client-side route change: it guarantees no
    // in-memory tenant data or open socket survives sign-out. AuthProvider sits
    // above RouterProvider, so useNavigate is not available here either.
    window.location.assign("/login");
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      role,
      isLoggedIn: token !== null,
      isLoading,
      login,
      logout,
    }),
    [user, token, role, isLoading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
