import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QcReport } from "@/components/QcReport";
import { ResultView } from "@/components/results/ResultView";
import { ErrorNote, KindMark } from "@/components/typography";
import { WeightsChart } from "@/components/charts/WeightsChart";
import { ApiError, api } from "@/lib/api";
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

  it.each([
    { usable: 30_000, fraction: 30_000 / 417_935, count: /30\s000/, coverage: "7.2%" },
    { usable: 0, fraction: 0, count: /^0$/, coverage: "0.0%" },
  ])("shows the API's SNP count and coverage separately ($usable usable)", ({ usable, fraction, count, coverage }) => {
    render(<QcReport dataset={{ ...synthDataset, qc: {
      ...synthDataset.qc, panel_size: 417_935, panel_overlap: fraction,
      overlap: { n_usable: usable },
    } }} />);
    expect(within(screen.getByRole("row", { name: /SNPs on reference panel/ })).getByRole("cell", { name: count })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Panel coverage/ })).toHaveTextContent(coverage);
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
    expect(screen.getByText("infeasible")).toBeInTheDocument();
    expect(screen.getByText(/Infeasible weights/)).toBeInTheDocument();
    expect(screen.getByText(/No weight figure is drawn/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /qpAdm weights/ })).toBeNull();
    expect(screen.getByText("1.120 ± 0.200")).toBeInTheDocument();
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

  it("states a panel limit above a formal result", async () => {
    vi.spyOn(api, "panel").mockResolvedValue({
      reference_version: "synthetic-test-v1",
      right_set: ["SynC"],
      limits: [
        { id: "no_aasi_proxy", summary: "No Andamanese-related population.", affects: ["qpadm"] },
      ],
    });
    render(<ResultView result={synthQpAdm} />);
    expect(await screen.findByText(/No Andamanese-related population/)).toBeInTheDocument();
  });

  it("does not imply a limit when the panel reports none", async () => {
    vi.spyOn(api, "panel").mockResolvedValue({
      reference_version: "synthetic-test-v1",
      right_set: [],
      limits: [],
    });
    render(<ResultView result={synthQpAdm} />);
    await screen.findByText("infeasible");
    expect(screen.queryByText(/cannot answer this fully/)).toBeNull();
  });

  it("hides a limit that names another analysis", async () => {
    vi.spyOn(api, "panel").mockResolvedValue({
      reference_version: "synthetic-test-v1",
      right_set: [],
      limits: [{ id: "elsewhere", summary: "Only f4.", affects: ["f4"] }],
    });
    render(<ResultView result={synthQpAdm} />);
    await screen.findByText("infeasible");
    expect(screen.queryByText(/Only f4/)).toBeNull();
  });

  it("still shows the result when the limits cannot be loaded", async () => {
    vi.spyOn(api, "panel").mockRejectedValue(new ApiError(503, "no reference"));
    render(<ResultView result={synthQpAdm} />);
    expect(await screen.findByText("infeasible")).toBeInTheDocument();
    expect(screen.queryByText(/cannot answer this fully/)).toBeNull();
  });

  it("shows unreachable API guidance", () => {
    render(<ErrorNote error={new ApiError(0, "down")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/NEXT_PUBLIC_API_URL/);
  });
});
