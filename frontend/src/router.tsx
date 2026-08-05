import { createRouter, createRootRoute, createRoute, redirect, lazyRouteComponent } from "@tanstack/react-router";
import { AppLayout } from "./components/layout/AppLayout";
import { isAuthenticated, getRole } from "./services/auth";
import NotFoundPage from "./pages/NotFoundPage";

// Root route
const rootRoute = createRootRoute({
  notFoundComponent: NotFoundPage,
});

// Login route (no layout)
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  beforeLoad: () => {
    if (isAuthenticated()) throw redirect({ to: "/dashboard" });
  },
  component: lazyRouteComponent(() => import("./pages/LoginPage")),
});

// Layout route (wraps all authenticated pages)
const layoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "layout",
  component: AppLayout,
  beforeLoad: () => {
    if (!isAuthenticated()) throw redirect({ to: "/login" });
  },
});

// Index redirect
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: isAuthenticated() ? "/dashboard" : "/login" });
  },
});

// Protected pages
const dashboardRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/dashboard",
  component: lazyRouteComponent(() => import("./pages/DashboardPage")),
});

const telemetryRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/telemetry",
  component: lazyRouteComponent(() => import("./pages/TelemetryPage")),
});

const incidentsRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/incidents",
  component: lazyRouteComponent(() => import("./pages/IncidentsPage")),
});

const incidentDetailRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/incidents/$id",
  component: lazyRouteComponent(() => import("./pages/IncidentDetailPage")),
});

const threatsRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/threats",
  component: lazyRouteComponent(() => import("./pages/ThreatsPage")),
});

const fleetRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/fleet",
  component: lazyRouteComponent(() => import("./pages/FleetPage")),
});

const adminRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/admin",
  beforeLoad: () => {
    const role = getRole();
    if (role !== "admin" && role !== "commander") {
      throw redirect({ to: "/dashboard" });
    }
  },
  component: lazyRouteComponent(() => import("./pages/AdminPage")),
});

const profileRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/profile",
  component: lazyRouteComponent(() => import("./pages/ProfilePage")),
});

const settingsRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/settings",
  beforeLoad: () => {
    const role = getRole();
    if (role !== "admin" && role !== "commander") {
      throw redirect({ to: "/dashboard" });
    }
  },
  component: lazyRouteComponent(() => import("./pages/SettingsPage")),
});

// Build route tree
const routeTree = rootRoute.addChildren([
  indexRoute,
  loginRoute,
  layoutRoute.addChildren([dashboardRoute, telemetryRoute, incidentsRoute, incidentDetailRoute, threatsRoute, fleetRoute, adminRoute, profileRoute, settingsRoute]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

