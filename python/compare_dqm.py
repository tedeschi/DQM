#!/usr/bin/env python
"""Dash app that lists Mu2e DQM datasets from metacat."""

from __future__ import annotations

import base64
import os
import subprocess
import shlex
import tempfile
import uuid
from pathlib import Path

try:
    from dash import Dash, Input, Output, State, callback, dcc, html, no_update
except ImportError as exc:
    raise SystemExit("Failed to import dash. Install it in your runtime environment.") from exc

DATASET_CMD = 'metacat dataset list "mu2e:dqm.mu2e.*"'
PREFIX = "mu2e:dqm.mu2e."
CHOOSE_NEW_FILE_MESSAGE = "choose new file"
CHOOSE_NEW_HISTOGRAM_MESSAGE = "choose new histogram"
COMPARE_HISTOGRAMS_FOUND_MESSAGE = "All compare histograms found."
GRID_GEOMETRIES = {
    "2x2": (2, 2),
    "3x3": (3, 3),
}


def dataset_label(dataset_name: str) -> str:
    if dataset_name.startswith(PREFIX):
        return dataset_name[len(PREFIX) :]
    return dataset_name


def file_label(file_path: str) -> str:
    if file_path.startswith("file://"):
        file_path = file_path[len("file://") :]
    return os.path.basename(file_path)


def selected_histograms(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [hist_name for hist_name in value if hist_name]
    return [value]


def grid_shape(grid_geometry: str | None) -> tuple[int, int]:
    return GRID_GEOMETRIES.get(grid_geometry or "2x2", GRID_GEOMETRIES["2x2"])


def grid_capacity(grid_geometry: str | None) -> int:
    rows, columns = grid_shape(grid_geometry)
    return rows * columns


def displayed_histograms(value, grid_geometry: str | None) -> list[str]:
    return selected_histograms(value)[: grid_capacity(grid_geometry)]


def histogram_selection_label(hist_names: list[str]) -> str:
    if not hist_names:
        return "none"
    if len(hist_names) <= 3:
        return ", ".join(hist_names)
    return f"{len(hist_names)} selected: {', '.join(hist_names[:3])}, ..."


def load_datasets() -> tuple[list[str], str]:
    """Return full dataset names and a status message."""
    try:
        result = subprocess.run(
            ["bash", "-lc", DATASET_CMD],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [], "bash is not available in this environment."
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip() or "Unknown error"
        return [], f"Dataset query failed: {stderr}"

    raw_names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not raw_names:
        return [], "No datasets returned by metacat."

    return raw_names, f"Loaded {len(raw_names)} datasets."


def load_files(dataset_name: str) -> tuple[list[dict[str, str]], str]:
    """Return dropdown options for files in the selected metacat dataset."""
    try:
        result = subprocess.run(
            ["bash", "-lc", f"metacat dataset files {shlex.quote(dataset_name)}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [], "bash is not available in this environment."
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip() or "Unknown error"
        return [], f"File query failed: {stderr}"

    files = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    if not files:
        return [], "No files returned by metacat."

    try:
        url_result = subprocess.run(
            ["bash", "-lc", "mdh print-url -l disk -"],
            input="\n".join(files) + "\n",
            check=True,
            capture_output=True,
            text=True,
        )
        urls = [line.strip() for line in url_result.stdout.splitlines() if line.strip()]
    except (FileNotFoundError, subprocess.CalledProcessError):
        urls = []

    values = urls if len(urls) == len(files) else files
    options = [
        {"label": file_label(value), "value": value}
        for value in sorted(values, key=file_label)
    ]
    source = "disk URLs" if len(urls) == len(files) else "metacat files"
    return options, f"Loaded {len(options)} {source}."


def load_histogram_names(root_path: str | Path) -> tuple[list[str], str]:
    """Return histogram names in a ROOT file."""
    try:
        import ROOT
    except Exception as exc:
        return [], f"Missing dependency: PyROOT is required: {exc}"

    path_str = str(root_path)
    if path_str.startswith("file://"):
        path_str = path_str[len("file://") :]

    if not (path_str.startswith("root://") or path_str.startswith("http://") or path_str.startswith("https://")):
        if not Path(path_str).exists():
            return [], f"ROOT file not found: {path_str}"

    ROOT.gROOT.SetBatch(True)
    ROOT.TH1.AddDirectory(False)
    ROOT.gROOT.cd()

    try:
        root_file = ROOT.TFile.Open(path_str, "READ")
    except TypeError:
        root_file = ROOT.TFile.Open(path_str)

    if not root_file or root_file.IsZombie():
        return [], f"Unable to open ROOT file: {path_str}"

    histogram_names: list[str] = []

    def walk_dir(directory: "ROOT.TDirectory", prefix: str = "") -> None:
        for key in directory.GetListOfKeys():
            name = key.GetName()
            obj = key.ReadObj()
            if obj.InheritsFrom("TDirectory"):
                walk_dir(obj, f"{prefix}{name}/")
                continue
            if obj.InheritsFrom("TH1") or obj.InheritsFrom("TProfile"):
                histogram_names.append(f"{prefix}{name}")

    try:
        walk_dir(root_file)
    finally:
        root_file.Close()

    histogram_names.sort()
    if not histogram_names:
        return [], "No histograms found in file."
    return histogram_names, f"Loaded {len(histogram_names)} histograms."


def histograms_exist(root_path: str | Path, hist_names: list[str]) -> tuple[list[str], str]:
    histograms, status = load_histogram_names(root_path)
    if not histograms:
        return hist_names, status
    available_histograms = set(histograms)
    missing_histograms = [
        hist_name for hist_name in hist_names if hist_name not in available_histograms
    ]
    return missing_histograms, status


def render_histogram_image(
    root_path: str | Path,
    hist_name: str,
    compare_path: str | Path | None = None,
    primary_label: str | None = None,
    compare_label: str | None = None,
    normalize_compare: bool = False,
    ignore_zero_bin: bool = False,
    ks_test: bool = False,
    frac_diff: bool = False,
) -> str:
    """Render a ROOT histogram to a browser-displayable PNG data URL."""
    try:
        import ROOT
    except Exception as exc:
        raise RuntimeError(f"Missing dependency: PyROOT is required: {exc}") from exc

    def normalize(path: str | Path) -> str:
        normalized = str(path)
        if normalized.startswith("file://"):
            return normalized[len("file://") :]
        return normalized

    def validate_path(path: str, label: str) -> None:
        if not (path.startswith("root://") or path.startswith("http://") or path.startswith("https://")):
            if not Path(path).exists():
                raise FileNotFoundError(f"{label} ROOT file not found: {path}")

    def set_sqrt_bin_errors(histogram) -> None:
        for bin_idx in range(1, histogram.GetNbinsX() + 1):
            counts = histogram.GetBinContent(bin_idx)
            histogram.SetBinError(bin_idx, counts ** 0.5 if counts >= 0 else 0.0)

    def histogram_total(histogram) -> float:
        return sum(
            histogram.GetBinContent(bin_idx)
            for bin_idx in range(1, histogram.GetNbinsX() + 1)
        )

    def fractional_difference_probability(hist1, hist2) -> float:
        sum1 = histogram_total(hist1)
        sum2 = histogram_total(hist2)
        if sum1 == 0 or sum2 == 0:
            return 0.0

        max_diff = 0.0
        s1 = 0.0
        s2 = 0.0
        upper_bin = min(hist1.GetNbinsX(), hist2.GetNbinsX())
        for bin_idx in range(1, upper_bin + 1):
            s1 += hist1.GetBinContent(bin_idx)
            s2 += hist2.GetBinContent(bin_idx)
            max_diff = max(max_diff, abs(s1 - s2))

        if s1 == 0:
            return 0.0
        return max(0.0, 1.0 - max_diff / s1)

    def clone_for_display(histogram, clone_name: str):
        ROOT.gROOT.cd()
        cloned_obj = histogram.Clone(clone_name)
        if hasattr(cloned_obj, "SetDirectory"):
            cloned_obj.SetDirectory(0)
        cloned_obj.SetName(clone_name)
        return cloned_obj

    def clear_zero_bin(histogram) -> None:
        zero_bin = histogram.GetXaxis().FindBin(0.0)
        if 1 <= zero_bin <= histogram.GetNbinsX():
            histogram.SetBinContent(zero_bin, 0.0)
            histogram.SetBinError(zero_bin, 0.0)

    path_str = normalize(root_path)
    compare_str = normalize(compare_path) if compare_path else None
    validate_path(path_str, "Primary")
    if compare_str:
        validate_path(compare_str, "Compare")

    ROOT.gROOT.SetBatch(True)
    ROOT.TH1.AddDirectory(False)
    ROOT.gStyle.SetOptStat(1111)
    ROOT.gROOT.cd()

    canvas = None
    tmp_path = None
    root_file = None
    compare_file = None
    try:
        unique_name = uuid.uuid4().hex

        def open_file(path: str, label: str):
            try:
                opened_file = ROOT.TFile.Open(path, "READ")
            except TypeError:
                opened_file = ROOT.TFile.Open(path)
            if not opened_file or opened_file.IsZombie():
                raise RuntimeError(f"Unable to open {label} ROOT file: {path}")
            return opened_file

        def clone_histogram(source_file, clone_name: str, missing_message: str):
            source_obj = source_file.Get(hist_name)
            if not source_obj:
                raise RuntimeError(missing_message)
            if not (source_obj.InheritsFrom("TH1") or source_obj.InheritsFrom("TProfile")):
                raise RuntimeError(f"Object is not a histogram: {hist_name}")
            ROOT.gROOT.cd()
            cloned_obj = source_obj.Clone(clone_name)
            if hasattr(cloned_obj, "SetDirectory"):
                cloned_obj.SetDirectory(0)
            cloned_obj.SetName(clone_name)
            return cloned_obj

        root_file = open_file(path_str, "primary")
        hist_obj = clone_histogram(
            root_file,
            f"primary_histogram_to_draw_{unique_name}",
            f"Histogram not found: {hist_name}",
        )

        canvas = ROOT.TCanvas(f"hist_canvas_{unique_name}", "Histogram", 900, 650)
        hist_obj.SetLineColor(ROOT.kBlack)
        hist_obj.SetLineWidth(2)
        hist_obj.SetMarkerColor(ROOT.kBlack)
        hist_obj.SetTitle(hist_name)
        if hasattr(hist_obj, "SetStats"):
            hist_obj.SetStats(True)

        compare_obj = None
        compare_scale_factor = None
        if compare_str:
            compare_file = open_file(compare_str, "compare")
            compare_obj = clone_histogram(
                compare_file,
                f"compare_histogram_to_draw_{unique_name}",
                "no histogram found",
            )
            compare_obj.SetLineColor(ROOT.kBlue)
            compare_obj.SetMarkerColor(ROOT.kBlue)
            compare_obj.SetMarkerStyle(20)
            compare_obj.SetMarkerSize(0.8)
            if hasattr(compare_obj, "SetStats"):
                compare_obj.SetStats(False)
            set_sqrt_bin_errors(compare_obj)
            if normalize_compare:
                compare_scale_factor = 0.0
                compare_total = histogram_total(compare_obj)
                if compare_total != 0:
                    compare_scale_factor = histogram_total(hist_obj) / compare_total
                    compare_obj.Scale(compare_scale_factor)

        display_hist_obj = hist_obj
        display_compare_obj = compare_obj
        if ignore_zero_bin:
            display_hist_obj = clone_for_display(
                hist_obj,
                f"primary_display_histogram_{unique_name}",
            )
            clear_zero_bin(display_hist_obj)
            if compare_obj is not None:
                display_compare_obj = clone_for_display(
                    compare_obj,
                    f"compare_display_histogram_{unique_name}",
                )
                clear_zero_bin(display_compare_obj)

        if display_compare_obj is not None:
            max_y = max(display_hist_obj.GetMaximum(), display_compare_obj.GetMaximum())
            if max_y > 0:
                display_hist_obj.SetMaximum(max_y * 1.15)

        display_hist_obj.Draw("HIST")
        legend = ROOT.TLegend(0.12, 0.79, 0.52, 0.9)
        legend.SetBorderSize(0)
        legend.SetFillStyle(0)
        legend.SetTextSize(0.025)
        if display_compare_obj is not None:
            display_compare_obj.Draw("E1 P SAME")
            legend.AddEntry(display_hist_obj, f"Display: {primary_label or file_label(path_str)}", "l")
            legend.AddEntry(display_compare_obj, f"Compare: {compare_label or file_label(compare_str)}", "lep")
        else:
            legend.AddEntry(display_hist_obj, hist_name, "l")

        legend.Draw()
        stat_lines = []
        if compare_obj is not None and compare_scale_factor is not None:
            stat_lines.append(f"A-norm={compare_scale_factor:.4g}")
        if compare_obj is not None and ks_test:
            ks_pvalue = hist_obj.KolmogorovTest(compare_obj)
            stat_lines.append(f"KS-test p-value: {ks_pvalue:.4g}")
        if compare_obj is not None and frac_diff:
            fr_prob = fractional_difference_probability(hist_obj, compare_obj)
            stat_lines.append(f"Frac-Diff: {fr_prob:.4g}")

        if stat_lines:
            stat_text = ROOT.TLatex()
            stat_text.SetNDC(True)
            stat_text.SetTextSize(0.03)
            stat_text.SetTextAlign(33)
            plot_right_edge = 1.0 - canvas.GetRightMargin()
            for line_idx, stat_line in enumerate(stat_lines):
                stat_text.DrawLatex(plot_right_edge, 0.765 - 0.04 * line_idx, stat_line)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        canvas.Modified()
        canvas.Update()
        canvas.SaveAs(tmp_path)
        with open(tmp_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    finally:
        if canvas is not None:
            canvas.Close()
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        if root_file:
            root_file.Close()
        if compare_file:
            compare_file.Close()


def build_app() -> Dash:
    app = Dash(__name__)

    initial_datasets, initial_status = load_datasets()

    app.layout = html.Div(
        [
            dcc.Store(id="file-load-status", data=""),
            dcc.Store(id="file-list-dataset", data=""),
            dcc.Store(id="histogram-load-status", data=""),
            dcc.Store(id="histogram-list-file", data=""),
            dcc.Store(id="plot-render-status", data=""),
            dcc.Store(id="displayed-plot-id", data=None),
            dcc.Store(id="compare-file-load-status", data=""),
            dcc.Store(id="compare-file-list-dataset", data=""),
            dcc.Store(id="compare-match-status", data=""),
            html.H1("DQM Tool"),
            html.Div(
                id="histogram-grid",
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
                    "gap": "12px",
                    "marginBottom": "20px",
                },
            ),
            html.H2("Datasets"),
            html.Div(
                initial_status,
                style={"marginTop": "12px", "fontFamily": "monospace"},
            ),
            dcc.Dropdown(
                id="dataset-dropdown",
                options=[
                    {"label": dataset_label(name), "value": name}
                    for name in initial_datasets
                ],
                value=None,
                placeholder="Select a dataset",
                style={"marginTop": "12px", "maxWidth": "900px"},
            ),
            html.Div(
                "Select a dataset.",
                id="dataset-status",
                style={"marginTop": "12px", "fontFamily": "monospace"},
            ),
            html.H2("Files"),
            dcc.Dropdown(
                id="file-dropdown",
                options=[],
                value=None,
                placeholder="Select a file",
                style={"marginTop": "12px", "maxWidth": "900px"},
            ),
            html.Div(
                "Select a dataset to list files.",
                id="file-status",
                style={"marginTop": "12px", "fontFamily": "monospace"},
            ),
            html.H2("Histograms in Selected File"),
            dcc.Dropdown(
                id="histogram-dropdown",
                options=[],
                value=[],
                multi=True,
                placeholder="Select histograms",
                style={"marginTop": "12px", "maxWidth": "900px"},
            ),
            html.Div(
                [
                    html.Span("Grid", style={"fontWeight": "bold"}),
                    dcc.RadioItems(
                        id="grid-geometry",
                        options=[
                            {"label": "2x2", "value": "2x2"},
                            {"label": "3x3", "value": "3x3"},
                        ],
                        value="2x2",
                        inline=True,
                        style={"display": "flex", "gap": "1rem"},
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "1rem",
                    "marginTop": "12px",
                },
            ),
            html.Div(
                "Select a file to list histograms.",
                id="histogram-status",
                style={"marginTop": "12px", "fontFamily": "monospace"},
            ),
            html.H2("Compare Dataset"),
            dcc.Dropdown(
                id="compare-dataset-dropdown",
                options=[
                    {"label": dataset_label(name), "value": name}
                    for name in initial_datasets
                ],
                value=None,
                placeholder="Select a compare dataset",
                style={"marginTop": "12px", "maxWidth": "900px"},
            ),
            html.H2("Compare File"),
            dcc.Dropdown(
                id="compare-file-dropdown",
                options=[],
                value=None,
                placeholder="Select a compare file",
                style={"marginTop": "12px", "maxWidth": "900px"},
            ),
            html.Div(
                [
                    dcc.Checklist(
                        id="compare-enabled",
                        options=[{"label": "Compare", "value": "compare", "disabled": True}],
                        value=[],
                    ),
                    dcc.Checklist(
                        id="ignore-zero-enabled",
                        options=[{"label": "Ingore-0", "value": "ignore_zero"}],
                        value=[],
                    ),
                    dcc.Checklist(
                        id="normalize-enabled",
                        options=[{"label": "A-Norm", "value": "normalize"}],
                        value=[],
                    ),
                    dcc.Checklist(
                        id="frac-diff-enabled",
                        options=[{"label": "Frac-Diff", "value": "frac_diff"}],
                        value=[],
                    ),
                    dcc.Checklist(
                        id="ks-test-enabled",
                        options=[{"label": "KS test", "value": "ks"}],
                        value=[],
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "1rem",
                    "marginTop": "12px",
                },
            ),
            html.Div(
                "Select a compare dataset and file.",
                id="compare-file-status",
                style={"marginTop": "12px", "fontFamily": "monospace"},
            ),
        ],
        style={
            "padding": "20px",
            "fontFamily": "Helvetica, Arial, sans-serif",
            "maxWidth": "1000px",
        },
    )

    @callback(
        Output("dataset-status", "children"),
        Input("dataset-dropdown", "value"),
    )
    def update_dataset_status(dataset_name):
        if dataset_name:
            return f"Dataset: {dataset_name}"
        if initial_status and (
            "failed" in initial_status.lower()
            or "error" in initial_status.lower()
            or "no datasets" in initial_status.lower()
        ):
            return initial_status
        return "Select a dataset."

    @callback(
        Output("file-dropdown", "options"),
        Output("file-dropdown", "value"),
        Output("file-load-status", "data"),
        Output("file-list-dataset", "data"),
        Input("dataset-dropdown", "value"),
        State("displayed-plot-id", "data"),
    )
    def update_files(dataset_name, displayed_plot_id):
        if not dataset_name:
            return [], None, "", ""

        file_options, status = load_files(dataset_name)
        value = None
        if file_options:
            previous_label = (
                displayed_plot_id.get("file_label")
                if isinstance(displayed_plot_id, dict)
                else None
            )
            if previous_label:
                matching_options = [
                    option for option in file_options if option["label"] == previous_label
                ]
                if matching_options:
                    value = matching_options[0]["value"]
                else:
                    status = CHOOSE_NEW_FILE_MESSAGE
            else:
                value = file_options[0]["value"]
        return file_options, value, status, dataset_name

    @callback(
        Output("file-status", "children"),
        Input("dataset-dropdown", "value"),
        Input("file-dropdown", "value"),
        Input("file-load-status", "data"),
    )
    def update_file_status(dataset_name, file_path, file_load_status):
        if not dataset_name:
            return "Select a dataset to list files."
        if not file_path:
            return (
                f"Dataset: {dataset_name}\n"
                "File: none\n"
                f"{file_load_status or 'No file selected.'}"
            )
        return (
            f"Dataset: {dataset_name}\n"
            f"File: {file_path}\n"
            f"{file_load_status}"
        )

    @callback(
        Output("histogram-dropdown", "options"),
        Output("histogram-dropdown", "value"),
        Output("histogram-load-status", "data"),
        Output("histogram-list-file", "data"),
        Input("file-dropdown", "value"),
        Input("file-list-dataset", "data"),
        State("displayed-plot-id", "data"),
    )
    def update_histogram_options(file_path, file_list_dataset, displayed_plot_id):
        if not file_path or not file_list_dataset:
            return [], [], "", ""

        histograms, status = load_histogram_names(file_path)
        if not histograms:
            return [], [], status, file_path

        options = [{"label": name, "value": name} for name in histograms]
        value = []
        displayed_hist_names = []
        if isinstance(displayed_plot_id, dict):
            displayed_hist_names = selected_histograms(
                displayed_plot_id.get("hist_names")
                or displayed_plot_id.get("hist_name")
            )
        if displayed_hist_names:
            available_histograms = set(histograms)
            value = [
                hist_name
                for hist_name in displayed_hist_names
                if hist_name in available_histograms
            ]
            if len(value) != len(displayed_hist_names):
                status = CHOOSE_NEW_HISTOGRAM_MESSAGE
        return options, value, status, file_path

    @callback(
        Output("histogram-status", "children"),
        Input("dataset-dropdown", "value"),
        Input("file-dropdown", "value"),
        Input("histogram-dropdown", "value"),
        Input("grid-geometry", "value"),
        Input("histogram-load-status", "data"),
        Input("plot-render-status", "data"),
    )
    def update_histogram_status(
        dataset_name,
        file_path,
        hist_names,
        grid_geometry,
        histogram_load_status,
        plot_render_status,
    ):
        if not file_path:
            return "Select a file to list histograms."
        selected_hist_names = selected_histograms(hist_names)
        display_hist_names = displayed_histograms(hist_names, grid_geometry)
        if plot_render_status:
            status = plot_render_status
        elif selected_hist_names:
            status = histogram_load_status
        else:
            status = histogram_load_status or CHOOSE_NEW_HISTOGRAM_MESSAGE
        if len(selected_hist_names) > len(display_hist_names):
            status = (
                f"{status}\n"
                f"Displaying first {len(display_hist_names)} of "
                f"{len(selected_hist_names)} selected histograms."
            )
        return (
            f"Dataset: {dataset_name or 'none'}\n"
            f"File: {file_path}\n"
            f"Histograms: {histogram_selection_label(display_hist_names)}\n"
            f"{status}"
        )

    @callback(
        Output("compare-file-dropdown", "options"),
        Output("compare-file-dropdown", "value"),
        Output("compare-file-load-status", "data"),
        Output("compare-file-list-dataset", "data"),
        Input("compare-dataset-dropdown", "value"),
        State("displayed-plot-id", "data"),
        State("compare-file-dropdown", "value"),
    )
    def update_compare_files(compare_dataset_name, displayed_plot_id, current_compare_file):
        if not compare_dataset_name:
            return [], None, "", ""

        file_options, status = load_files(compare_dataset_name)
        value = None
        if file_options:
            preferred_label = None
            if isinstance(displayed_plot_id, dict):
                preferred_label = (
                    displayed_plot_id.get("compare_file_label")
                    or displayed_plot_id.get("file_label")
                )
            if not preferred_label and current_compare_file:
                preferred_label = file_label(current_compare_file)

            if preferred_label:
                matching_options = [
                    option for option in file_options if option["label"] == preferred_label
                ]
                if matching_options:
                    value = matching_options[0]["value"]
                elif isinstance(displayed_plot_id, dict):
                    status = CHOOSE_NEW_FILE_MESSAGE
            else:
                value = file_options[0]["value"]
        return file_options, value, status, compare_dataset_name

    @callback(
        Output("compare-enabled", "options"),
        Output("compare-enabled", "value"),
        Output("compare-match-status", "data"),
        Input("compare-file-dropdown", "value"),
        Input("histogram-dropdown", "value"),
        Input("grid-geometry", "value"),
        State("compare-enabled", "value"),
    )
    def update_compare_availability(
        compare_file_path,
        hist_names,
        grid_geometry,
        compare_enabled,
    ):
        disabled_options = [
            {"label": "Compare", "value": "compare", "disabled": True}
        ]
        enabled_options = [
            {"label": "Compare", "value": "compare", "disabled": False}
        ]
        display_hist_names = displayed_histograms(hist_names, grid_geometry)

        if not compare_file_path:
            return disabled_options, [], "Select a compare file."
        if not display_hist_names:
            return disabled_options, [], "Display one or more histograms first."

        missing_histograms, _status = histograms_exist(compare_file_path, display_hist_names)
        if missing_histograms:
            missing_label = histogram_selection_label(missing_histograms)
            return disabled_options, [], f"Missing compare histograms: {missing_label}"

        value = compare_enabled if compare_enabled and "compare" in compare_enabled else []
        return enabled_options, value, COMPARE_HISTOGRAMS_FOUND_MESSAGE

    @callback(
        Output("compare-file-status", "children"),
        Input("compare-dataset-dropdown", "value"),
        Input("compare-file-dropdown", "value"),
        Input("compare-file-load-status", "data"),
        Input("compare-match-status", "data"),
        Input("histogram-dropdown", "value"),
        Input("grid-geometry", "value"),
    )
    def update_compare_file_status(
        compare_dataset_name,
        compare_file_path,
        compare_file_load_status,
        compare_match_status,
        hist_names,
        grid_geometry,
    ):
        if not compare_dataset_name:
            return "Select a compare dataset."
        display_hist_names = displayed_histograms(hist_names, grid_geometry)
        if not compare_file_path:
            return (
                f"Compare dataset: {compare_dataset_name}\n"
                "Compare file: none\n"
                f"{compare_file_load_status or 'No compare file selected.'}"
            )

        return (
            f"Compare dataset: {compare_dataset_name}\n"
            f"Compare file: {compare_file_path}\n"
            f"Histograms: {histogram_selection_label(display_hist_names)}\n"
            f"{compare_match_status or compare_file_load_status}"
        )

    @callback(
        Output("histogram-grid", "children"),
        Output("histogram-grid", "style"),
        Output("displayed-plot-id", "data"),
        Output("plot-render-status", "data"),
        Input("dataset-dropdown", "value"),
        Input("file-dropdown", "value"),
        Input("histogram-dropdown", "value"),
        Input("grid-geometry", "value"),
        Input("file-list-dataset", "data"),
        Input("histogram-list-file", "data"),
        Input("compare-dataset-dropdown", "value"),
        Input("compare-file-dropdown", "value"),
        Input("compare-file-list-dataset", "data"),
        Input("compare-enabled", "value"),
        Input("ignore-zero-enabled", "value"),
        Input("normalize-enabled", "value"),
        Input("frac-diff-enabled", "value"),
        Input("ks-test-enabled", "value"),
        Input("compare-match-status", "data"),
    )
    def update_histogram_image(
        dataset_name,
        file_path,
        hist_names,
        grid_geometry,
        file_list_dataset,
        histogram_list_file,
        compare_dataset_name,
        compare_file_path,
        compare_file_list_dataset,
        compare_enabled,
        ignore_zero_enabled,
        normalize_enabled,
        frac_diff_enabled,
        ks_test_enabled,
        compare_match_status,
    ):
        rows, columns = grid_shape(grid_geometry)
        grid_style = {
            "display": "grid",
            "gridTemplateColumns": f"repeat({columns}, minmax(0, 1fr))",
            "gap": "12px",
            "marginBottom": "20px",
        }
        selected_hist_names = selected_histograms(hist_names)
        display_hist_names = selected_hist_names[: rows * columns]

        if not file_path or not display_hist_names:
            return [], grid_style, no_update, ""
        if dataset_name != file_list_dataset or file_path != histogram_list_file:
            return [], grid_style, no_update, ""

        compare_path = None
        if (
            compare_enabled
            and "compare" in compare_enabled
            and compare_match_status == COMPARE_HISTOGRAMS_FOUND_MESSAGE
            and compare_file_path
            and compare_dataset_name == compare_file_list_dataset
        ):
            compare_path = compare_file_path

        try:
            image_children = []
            for hist_name in display_hist_names:
                image_src = render_histogram_image(
                    file_path,
                    hist_name,
                    compare_path,
                    primary_label=file_label(file_path),
                    compare_label=file_label(compare_path) if compare_path else None,
                    normalize_compare=bool(
                        compare_path
                        and normalize_enabled
                        and "normalize" in normalize_enabled
                    ),
                    ignore_zero_bin=bool(
                        ignore_zero_enabled
                        and "ignore_zero" in ignore_zero_enabled
                    ),
                    ks_test=bool(
                        compare_path
                        and ks_test_enabled
                        and "ks" in ks_test_enabled
                    ),
                    frac_diff=bool(
                        compare_path
                        and frac_diff_enabled
                        and "frac_diff" in frac_diff_enabled
                    ),
                )
                image_children.append(
                    html.Img(
                        src=image_src,
                        alt=hist_name,
                        style={
                            "width": "100%",
                            "maxWidth": "100%",
                            "border": "1px solid #ccc",
                            "padding": "0.5rem",
                            "background": "#fff",
                            "boxSizing": "border-box",
                        },
                    )
                )
        except Exception as exc:
            return [], grid_style, no_update, f"Error rendering histogram: {exc}"

        plot_id = {
            "dataset": dataset_name,
            "file_path": file_path,
            "file_label": file_label(file_path),
            "hist_names": selected_hist_names,
            "displayed_hist_names": display_hist_names,
            "grid_geometry": grid_geometry,
        }
        if compare_path:
            plot_id.update(
                {
                    "compare_dataset": compare_dataset_name,
                    "compare_file_path": compare_path,
                    "compare_file_label": file_label(compare_path),
                }
            )

        return (
            image_children,
            grid_style,
            plot_id,
            "",
        )

    return app


def main() -> None:
    app = build_app()
    app.run(
        host="127.0.0.1",
        port=8050,
        debug=False,
        threaded=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
