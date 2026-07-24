import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/screens/$slug", params: { slug: "secure_login" } });
  },
  component: () => null,
});
