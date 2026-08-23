import { Link } from "@tanstack/react-router";
import { Icon } from "@/components/ui/Icon";
import { isAuthenticated } from "@/services/auth";

export default function NotFoundPage() {
  const signedIn = isAuthenticated();

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md rounded-panel border border-line bg-surface-raised p-6 text-center">
        <Icon name="info" size={20} className="mx-auto text-content-dim" />
        <h1 className="mt-3 text-[16px] font-semibold text-content">Page not found</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-content-muted">
          That address does not match any view in the console. It may have been renamed, or the link
          may be out of date.
        </p>

        <div className="mt-5 flex justify-center gap-2">
          <Link
            to={signedIn ? "/dashboard" : "/login"}
            className="rounded-control border border-accent/50 bg-accent-dim px-3 py-1.5 text-[13px] text-content hover:bg-accent/25"
          >
            {signedIn ? "Go to dashboard" : "Go to sign in"}
          </Link>
          {signedIn ? (
            <Link
              to="/incidents"
              className="rounded-control border border-line-strong bg-surface-overlay px-3 py-1.5 text-[13px] text-content hover:bg-surface-hover"
            >
              View incidents
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
