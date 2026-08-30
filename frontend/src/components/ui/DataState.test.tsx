/**
 * Honest-state rendering.
 *
 * The point of DataState is that a failed request never renders as an empty
 * success. These tests pin each branch to a distinguishable message.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataState, ErrorState, UnavailableState } from "./DataState";
import { ApiError } from "@/services/api";

describe("DataState", () => {
  const renderList = (props: Partial<Parameters<typeof DataState<string[]>>[0]> = {}) =>
    render(
      <DataState<string[]>
        isLoading={false}
        isError={false}
        data={["alpha"]}
        {...props}
        children={(rows) => (
          <ul>
            {rows.map((row) => (
              <li key={row}>{row}</li>
            ))}
          </ul>
        )}
      />,
    );

  it("shows a loading indicator while the request is in flight", () => {
    renderList({ isLoading: true });
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  });

  it("renders the data once resolved", () => {
    renderList();
    expect(screen.getByText("alpha")).toBeInTheDocument();
  });

  it("distinguishes an empty result from a failure", () => {
    renderList({ data: [] });
    expect(screen.getByText("No records")).toBeInTheDocument();
    // Critically, this must not read as an error.
    expect(screen.queryByText("Request failed")).not.toBeInTheDocument();
  });

  it("reports a forbidden response as a permission problem, not a crash", () => {
    renderList({ isError: true, error: new ApiError("Permission denied", 403) });
    expect(screen.getByText("You do not have access to this")).toBeInTheDocument();
  });

  it("reports an unreachable server distinctly from a server error", () => {
    renderList({ isError: true, error: new ApiError("Cannot reach the server.", 0) });
    expect(screen.getByText("Cannot reach the server")).toBeInTheDocument();
  });

  it("reports a 404 as not found", () => {
    renderList({ isError: true, error: new ApiError("Missing", 404) });
    expect(screen.getByText("Not found")).toBeInTheDocument();
  });

  it("surfaces the message for an unclassified failure", () => {
    renderList({ isError: true, error: new ApiError("Database is on fire", 500) });
    expect(screen.getByText("Request failed")).toBeInTheDocument();
    expect(screen.getByText("Database is on fire")).toBeInTheDocument();
  });

  it("offers a retry that calls back", async () => {
    const onRetry = vi.fn();
    renderList({ isError: true, error: new ApiError("Boom", 500), onRetry });

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("honours a custom emptiness test", () => {
    render(
      <DataState<{ rows: string[] }>
        isLoading={false}
        isError={false}
        data={{ rows: [] }}
        isEmpty={(d) => d.rows.length === 0}
        children={() => <p>should not render</p>}
      />,
    );
    expect(screen.queryByText("should not render")).not.toBeInTheDocument();
    expect(screen.getByText("No records")).toBeInTheDocument();
  });
});

describe("UnavailableState", () => {
  it("states that the capability is absent rather than showing a placeholder", () => {
    render(
      <UnavailableState
        title="Not available"
        detail="This backend does not expose swarm formation."
      />,
    );
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(
      screen.getByText("This backend does not expose swarm formation."),
    ).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("falls back to a generic message for a non-Error value", () => {
    render(<ErrorState error={"something odd"} />);
    expect(screen.getByText("Request failed")).toBeInTheDocument();
  });
});
