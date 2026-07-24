import React, { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { login as authLogin, logout as authLogout, isAuthenticated, getRole, getToken } from "@/services/auth";
import { api, type UserInfo } from "@/services/api";

interface AuthContextType {
  user: UserInfo | null;
  token: string | null;
  role: string | null;
  isLoggedIn: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (isAuthenticated()) {
      api.getMe()
        .then(setUser)
        .catch(() => {
          authLogout();
          setUser(null);
        })
        .finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    await authLogin(username, password);
    const me = await api.getMe();
    setUser(me);
  }, []);

  const logout = useCallback(() => {
    authLogout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        token: getToken(),
        role: getRole(),
        isLoggedIn: isAuthenticated(),
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
