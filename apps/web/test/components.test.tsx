import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QcReport } from "@/components/QcReport";
import { ResultView } from "@/components/results/ResultView";
import { ErrorNote, KindMark } from "@/components/typography";
import { WeightsChart } from "@/components/charts/WeightsChart";
import { ApiError } from "@/lib/api";
import { synthDataset, synthFit, synthNearest, synthQpAdm } from "./fixtures";

vi.mock("next/dynamic", () => ({ default: () => () => null }));

describe("components", () => {
  it("renders a QC report as a table with warnings", () => {
    render(<QcReport dataset={synthDataset} />);
    expect(screen.getByText("Table 1.")).toBeInTheDocument();
    expect(screen.getByText("23andMe v5")).toBeInTheDocument();
    expect(screen.getByText("98.50%")).toBeInTheDocument();
    expect(screen.getByText("synthetic warning")).toBeInTheDocument();
  });

  it("labels results as exploratory or formal", () => {
    render(<KindMark kind="formal" />);
    expect(screen.getByText("formal")).toHaveAttribute("title", expect.stringMatching(/qpAdm/));
  });

  it("renders a nearest-population table with an exploratory caveat", () => {
    render(<ResultView result={synthNearest} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Synthetic A")).toBeInTheDocument();
    expect(screen.getByText("Exploratory result")).toBeInTheDocument();
  });

  it("renders an exploratory fit with interval table", () => {
    render(<ResultView result={synthFit} />);
    expect(screen.getByText("20.0% to 40.0%")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Mixture weights for SYNTH_target/ })).toBeInTheDocument();
  });

  it("marks a rejected, infeasible qpAdm model", () => {
    render(<ResultView result={synthQpAdm} />);
    expect(screen.getByText("rejected")).toBeInTheDocument();
    expect(screen.getByText(/Infeasible weights/)).toBeInTheDocument();
    expect(screen.getByText("112.0 ± 20.0")).toBeInTheDocument();
  });

  it("draws whiskers for each weight", () => {
    const { container } = render(
      <WeightsChart title="w" intervalLabel="CI" rows={[{ label: "A", weight: 0.4, lo: 0.3, hi: 0.5 }, { label: "B", weight: 0.6 }]} />,
    );
    // Three lines per whisker (span + two caps) for A only.
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-label")).toBe("w. A 40.0%, B 60.0%");
  });

  it("explains an unbuilt reference library without alarm", () => {
    const err = new ApiError(503, "x", { detail: "x", code: "reference_unavailable" });
    render(<ErrorNote error={err} retry={() => undefined} />);
    expect(screen.getByRole("status")).toHaveTextContent(/reference library has not been built/);
    expect(screen.queryByText("Try again")).toBeNull();
  });

  it("shows unreachable API guidance", () => {
    render(<ErrorNote error={new ApiError(0, "down")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/NEXT_PUBLIC_API_URL/);
  });
});
