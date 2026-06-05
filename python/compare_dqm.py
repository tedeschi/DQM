#!/usr/bin/env python
"""Dash app that builds a dataset dropdown from metacat output.

This is a pared-down version of :mod:`DqmMenu` intended to launch a
web page on port 8050 and simply display the dataset names in a
<select> control.  The underlying dataset query is:

    metacat dataset list mu2e:ntd.*

Names are stripped of the leading ``mu2e:ntd.mu2e.`` prefix for
readability.
"""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import uuid
import webbrowser
from pathlib import Path

try:
    from dash import Dash, Input, Output, callback, dcc, html
except ImportError as exc:
    raise SystemExit("Failed to import dash. Install it in your runtime environment.") from exc

DATASET_CMD = 'metacat dataset list "mu2e:dqm.mu2e.*"'
PREFIX = "mu2e:dqm.mu2e."
MISSING_COMPARE_HISTOGRAM_MESSAGE = "histogram does not exist in chosen file"


def load_datasets():
    """Return ``(datasets, status)`` where ``datasets`` is a list of
    cleaned-up names and ``status`` is a human-readable message.
    """

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

    raw = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not raw:
        return [], "No datasets returned by metacat."

    cleaned = []
    for ds in raw:
        if ds.startswith(PREFIX):
            cleaned.append(ds[len(PREFIX):])
        else:
            cleaned.append(ds)

    return cleaned, f"Loaded {len(cleaned)} datasets."


def load_files(dataset_full):
    """Return ``(files, status)`` for the given full dataset name."""
    cmd = f'metacat dataset files "{dataset_full}" | sort | mdh print-url -l disk -'
    try:
        result = subprocess.run(
            ["bash", "-lc", cmd],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [], "bash is not available in this environment."
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip() or "Unknown error"
        return [], f"File query failed: {stderr}"

    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not files:
        return [], "No files returned."

    return files, f"Loaded {len(files)} files."


def render_histogram_image(
    root_path: str | Path,
    hist_name: str,
    compare_path: str | Path | None = None,
    ks_test: bool = False,
) -> str:
    try:
        import ROOT
    except Exception as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError(
            "Missing dependency: PyROOT is required. "
            "Ensure ROOT is installed and available in your Python environment."
        ) from exc

    def normalize(path: str | Path) -> str:
        s = str(path)
        if s.startswith("file://"):
            return s[len("file://") :]
        return s

    primary_str = normalize(root_path)
    compare_str = normalize(compare_path) if compare_path is not None else None

    # Root can open xrootd/http URLs directly. Only validate local paths.
    if not (primary_str.startswith("root://") or primary_str.startswith("http://") or primary_str.startswith("https://")):
        if not Path(primary_str).exists():
            raise FileNotFoundError(f"ROOT file not found: {primary_str}")

    ROOT.gROOT.SetBatch(True)
    try:
        primary_file = ROOT.TFile.Open(primary_str, "READ")
    except TypeError:
        primary_file = ROOT.TFile.Open(primary_str)

    if not primary_file or primary_file.IsZombie():
        raise RuntimeError(f"Unable to open ROOT file: {primary_str}")

    compare_file = None
    try:
        clone_suffix = uuid.uuid4().hex

        def clone_histogram(source_file, source_name, clone_name, missing_message):
            source_obj = source_file.Get(source_name)
            if not source_obj:
                raise RuntimeError(missing_message)
            if not (source_obj.InheritsFrom("TH1") or source_obj.InheritsFrom("TProfile")):
                raise RuntimeError(f"Object is not a histogram: {source_name}")

            cloned_obj = source_obj.Clone(clone_name)
            if hasattr(cloned_obj, "SetDirectory"):
                cloned_obj.SetDirectory(0)
            return cloned_obj

        primary_obj = clone_histogram(
            primary_file,
            hist_name,
            f"primary_histogram_to_draw_{clone_suffix}",
            f"Histogram not found: {hist_name}",
        )

        compare_obj = None
        if compare_str:
            # Only validate local compare file paths, allow xrootd/http to pass through.
            if not (compare_str.startswith("root://") or compare_str.startswith("http://") or compare_str.startswith("https://")):
                if not Path(compare_str).exists():
                    raise FileNotFoundError(f"Compare ROOT file not found: {compare_str}")

            try:
                compare_file = ROOT.TFile.Open(compare_str, "READ")
            except TypeError:
                compare_file = ROOT.TFile.Open(compare_str)

            if not compare_file or compare_file.IsZombie():
                raise RuntimeError(f"Unable to open compare ROOT file: {compare_str}")

            compare_obj = clone_histogram(
                compare_file,
                hist_name,
                f"compare_histogram_to_draw_{clone_suffix}",
                MISSING_COMPARE_HISTOGRAM_MESSAGE,
            )

        canvas = ROOT.TCanvas("hist_canvas", "Histogram", 900, 650)
        primary_obj.SetLineColor(ROOT.kBlack)
        primary_obj.SetMarkerColor(ROOT.kBlack)
        primary_obj.SetLineWidth(2)

        if compare_obj is not None:
            max_y = max(primary_obj.GetMaximum(), compare_obj.GetMaximum())
            if max_y > 0:
                primary_obj.SetMaximum(max_y * 1.15)

        primary_obj.Draw("HIST")

        if compare_obj is not None:
            compare_obj.SetLineColor(ROOT.kBlue)
            compare_obj.SetMarkerColor(ROOT.kBlue)
            compare_obj.SetLineWidth(2)
            compare_obj.Draw("HIST SAME")

            legend = ROOT.TLegend(0.37, 0.78, 0.63, 0.9)
            legend.SetBorderSize(0)
            legend.SetFillStyle(0)
            legend.SetTextSize(0.02)
            legend.AddEntry(primary_obj, "Selected file", "l")
            legend.AddEntry(compare_obj, "Compare file", "l")
            legend.Draw()

            if ks_test:
                ks_pvalue = primary_obj.KolmogorovTest(compare_obj)
                ks_text = ROOT.TLatex()
                ks_text.SetNDC(True)
                ks_text.SetTextSize(0.035)
                # Show at least 4 digits of precision for the p-value.
                ks_text.DrawLatex(0.12, 0.92, f"KS-test p-value: {ks_pvalue:.4g}")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            canvas.SaveAs(tmp_path)
            with open(tmp_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
        finally:
            canvas.Close()
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        return f"data:image/png;base64,{encoded}"
    finally:
        primary_file.Close()
        if compare_file:
            compare_file.Close()


def load_histogram_names(root_path: str | Path) -> list[str]:
    try:
        import ROOT
    except Exception as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError(
            "Missing dependency: PyROOT is required. "
            "Ensure ROOT is installed and available in your Python environment."
        ) from exc

    path_str = str(root_path)

    # Allow ROOT to handle xrootd and other non-filesystem paths directly.
    if path_str.startswith("file://"):
        path_str = path_str[len("file://") :]

    if not (path_str.startswith("root://") or path_str.startswith("http://") or path_str.startswith("https://")):
        if not Path(path_str).exists():
            raise FileNotFoundError(f"ROOT file not found: {path_str}")

    histogram_names: list[str] = []
    try:
        root_file = ROOT.TFile.Open(path_str, "READ")
    except TypeError:
        # Some ROOT/PyROOT bindings only accept a single string argument.
        root_file = ROOT.TFile.Open(path_str)

    if not root_file or root_file.IsZombie():
        raise RuntimeError(f"Unable to open ROOT file: {path_str}")

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
    return histogram_names


def build_app():
    app = Dash(__name__)

    initial_datasets, initial_status = load_datasets()
    initial_value = initial_datasets[0] if initial_datasets else None

    app.layout = html.Div(
        [
            html.Img(
                id="histogram-image",
                style={
                    "maxWidth": "100%",
                    "border": "1px solid #ccc",
                    "padding": "0.5rem",
                    "background": "#fff",
                    "marginBottom": "20px",
                },
            ),
            html.H2("Mu2e Datasets"),
            html.P(
                "Entries come from the local shell command ``{}``.".format(DATASET_CMD)
            ),
            html.Div(
                [
                    html.Button("Refresh", id="refresh-button", n_clicks=0),
                    html.Div(
                        initial_status,
                        id="status-message",
                        style={"marginTop": "12px", "fontFamily": "monospace"},
                    ),
                ],
                style={"marginBottom": "18px"},
            ),
            dcc.Dropdown(
                id="dataset-dropdown",
                options=[{"label": name, "value": name} for name in initial_datasets],
                value=initial_value,
                placeholder="Select a dataset",
                style={"maxWidth": "900px"},
            ),
            html.Pre(
                initial_value or "No dataset selected.",
                id="selected-dataset",
                style={
                    "marginTop": "20px",
                    "padding": "12px",
                    "backgroundColor": "#f2f2f2",
                    "border": "1px solid #cccccc",
                    "maxWidth": "900px",
                    "whiteSpace": "pre-wrap",
                },
            ),
            html.H3("Files in Selected Dataset"),
            dcc.Dropdown(
                id="file-dropdown",
                options=[],
                value=None,
                placeholder="Select a file",
                style={"maxWidth": "900px"},
            ),
            html.Pre(
                "No file selected.",
                id="selected-file",
                style={
                    "marginTop": "20px",
                    "padding": "12px",
                    "backgroundColor": "#f2f2f2",
                    "border": "1px solid #cccccc",
                    "maxWidth": "900px",
                    "whiteSpace": "pre-wrap",
                },
            ),
            html.H3("Histograms in Selected File"),
            dcc.Dropdown(
                id="histogram-dropdown",
                options=[],
                value=None,
                placeholder="Select a histogram",
                style={"maxWidth": "900px"},
            ),
            html.Div(
                "",
                id="histogram-status",
                style={"marginTop": "12px", "fontFamily": "monospace"},
            ),
            html.Pre(
                "No histogram selected.",
                id="selected-histogram",
                style={
                    "marginTop": "20px",
                    "padding": "12px",
                    "backgroundColor": "#f2f2f2",
                    "border": "1px solid #cccccc",
                    "maxWidth": "900px",
                    "whiteSpace": "pre-wrap",
                },
            ),
            html.H3("Compare Dataset"),
            dcc.Dropdown(
                id="compare-dataset-dropdown",
                options=[{"label": name, "value": name} for name in initial_datasets],
                value=None,
                placeholder="Select a compare dataset",
                style={"maxWidth": "900px"},
            ),
            html.Pre(
                "No compare dataset selected.",
                id="selected-compare-dataset",
                style={
                    "marginTop": "20px",
                    "padding": "12px",
                    "backgroundColor": "#f2f2f2",
                    "border": "1px solid #cccccc",
                    "maxWidth": "900px",
                    "whiteSpace": "pre-wrap",
                },
            ),
            html.H3("Compare File"),
            dcc.Dropdown(
                id="compare-file-dropdown",
                options=[],
                value=None,
                placeholder="Select a compare file",
                style={"maxWidth": "900px"},
            ),
            html.Div(
                [
                    dcc.Checklist(
                        id="compare-enabled",
                        options=[{"label": "Compare", "value": "compare"}],
                        value=[],
                    ),
                    dcc.Checklist(
                        id="ks-test-enabled",
                        options=[{"label": "KS-test", "value": "ks"}],
                        value=[],
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "1rem",
                    "marginTop": "8px",
                    "marginBottom": "20px",
                },
            ),
            html.Div(
                "",
                id="comparison-status",
                style={
                    "marginTop": "12px",
                    "fontFamily": "monospace",
                    "color": "#b00020",
                },
            ),
            html.Pre(
                "No compare file selected.",
                id="selected-compare-file",
                style={
                    "marginTop": "20px",
                    "padding": "12px",
                    "backgroundColor": "#f2f2f2",
                    "border": "1px solid #cccccc",
                    "maxWidth": "900px",
                    "whiteSpace": "pre-wrap",
                },
            ),
        ],
        style={"padding": "20px", "fontFamily": "Helvetica, Arial, sans-serif"},
    )

    @callback(
        Output("dataset-dropdown", "options"),
        Output("dataset-dropdown", "value"),
        Output("compare-dataset-dropdown", "options"),
        Output("compare-dataset-dropdown", "value"),
        Output("status-message", "children"),
        Input("refresh-button", "n_clicks"),
    )
    def refresh(_n_clicks):
        datasets, status = load_datasets()
        options = [{"label": name, "value": name} for name in datasets]
        value = datasets[0] if datasets else None
        return options, value, options, None, status

    @callback(Output("selected-dataset", "children"), Input("dataset-dropdown", "value"))
    def show_selection(dataset_name):
        return dataset_name or "No dataset selected."

    @callback(
        Output("selected-compare-dataset", "children"),
        Input("compare-dataset-dropdown", "value"),
    )
    def show_compare_dataset_selection(dataset_name):
        return dataset_name or "No compare dataset selected."

    @callback(
        Output("file-dropdown", "options"),
        Output("file-dropdown", "value"),
        Input("dataset-dropdown", "value"),
    )
    def update_files(dataset_name):
        if not dataset_name:
            return [], None
        dataset_full = PREFIX + dataset_name
        files, _ = load_files(dataset_full)
        options = [{"label": os.path.basename(url), "value": url} for url in files]
        value = files[0] if files else None
        return options, value

    @callback(
        Output("compare-file-dropdown", "options"),
        Output("compare-file-dropdown", "value"),
        Input("compare-dataset-dropdown", "value"),
    )
    def update_compare_files(dataset_name):
        if not dataset_name:
            return [], None
        dataset_full = PREFIX + dataset_name
        files, _ = load_files(dataset_full)
        options = [{"label": os.path.basename(url), "value": url} for url in files]
        value = files[0] if files else None
        return options, value

    @callback(Output("selected-file", "children"), Input("file-dropdown", "value"))
    def show_file_selection(file_url):
        return file_url or "No file selected."

    @callback(Output("selected-compare-file", "children"), Input("compare-file-dropdown", "value"))
    def show_compare_file_selection(file_url):
        return file_url or "No compare file selected."

    @callback(
        Output("histogram-dropdown", "options"),
        Output("histogram-dropdown", "value"),
        Output("histogram-status", "children"),
        Input("file-dropdown", "value"),
    )
    def update_histograms(file_url):
        if not file_url:
            return [], None, ""

        # ROOT can open xrootd paths directly, but if we get a file:// URL we
        # need to strip the scheme for local disk paths.
        if file_url.startswith("file://"):
            file_url = file_url[len("file://") :]

        try:
            names = load_histogram_names(file_url)
        except Exception as exc:
            return [], None, f"Error loading histograms: {exc}"

        if not names:
            return [], None, "No histograms found in file."

        options = [{"label": name, "value": name} for name in names]
        value = names[0]
        return options, value, f"Loaded {len(names)} histograms."

    @callback(Output("selected-histogram", "children"), Input("histogram-dropdown", "value"))
    def show_histogram_selection(hist_name):
        return hist_name or "No histogram selected."

    @callback(
        Output("histogram-image", "src"),
        Output("comparison-status", "children"),
        Input("file-dropdown", "value"),
        Input("compare-file-dropdown", "value"),
        Input("compare-enabled", "value"),
        Input("ks-test-enabled", "value"),
        Input("histogram-dropdown", "value"),
    )
    def update_histogram_image(file_url, compare_file_url, compare_enabled, ks_test_enabled, hist_name):
        if not file_url or not hist_name:
            return "", ""

        compare_path = None
        ks_test = False
        if compare_file_url and compare_enabled and "compare" in compare_enabled:
            compare_path = compare_file_url
            ks_test = bool(ks_test_enabled and "ks" in ks_test_enabled)

        try:
            return render_histogram_image(file_url, hist_name, compare_path, ks_test), ""
        except RuntimeError as exc:
            if str(exc) == MISSING_COMPARE_HISTOGRAM_MESSAGE:
                print(MISSING_COMPARE_HISTOGRAM_MESSAGE)
                return (
                    render_histogram_image(file_url, hist_name),
                    MISSING_COMPARE_HISTOGRAM_MESSAGE,
                )
            raise

    return app


def main():
    app = build_app()
    # ROOT / PyROOT is not thread-safe, so run the server single-threaded.
    app.run(
        host="127.0.0.1",
        port=8050,
        debug=False,
        threaded=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
