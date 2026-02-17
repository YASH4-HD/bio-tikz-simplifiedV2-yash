import difflib
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageOps

st.set_page_config(page_title="Bio-TikZ Studio", page_icon="🧬", layout="wide")

OUTPUT_PROFILES = {
    "Custom": {"dpi_scale": 4, "auto_crop": True, "line_thickness": "thick"},
    "Nature Journal": {"dpi_scale": 6, "auto_crop": True, "line_thickness": "thin"},
    "Conference Poster": {"dpi_scale": 4, "auto_crop": True, "line_thickness": "ultra thick"},
    "Grant/Investor Deck": {"dpi_scale": 3, "auto_crop": True, "line_thickness": "thick"},
}

TIKZ_TEMPLATES = {
    "Mitochondria (Bezier)": r"""\begin{tikzpicture}
% Outer membrane
\draw[thick] (0,0) ellipse (4 and 2);
% Inner membrane (cristae style)
\draw[thick] (-3,0) 
.. controls (-2.5,1) and (-1.5,1) .. (-1,0)
.. controls (-0.5,-1) and (0.5,-1) .. (1,0)
.. controls (1.5,1) and (2.5,1) .. (3,0);
% Labels
\node at (0,2.4) {\textbf{Outer Membrane}};
\node at (0,-2.4) {\textbf{Inner Membrane}};
\node at (0,0.8) {\textit{Matrix}};
\end{tikzpicture}""",
    "Cell Signaling": r"""\begin{tikzpicture}
\node[circle, draw, fill=blue!15, minimum size=2.2cm] (cell) at (0,0) {Cell};
\node[rectangle, draw, fill=green!20, minimum width=1.5cm, minimum height=0.6cm] (rec) at (0,1.8) {Receptor};
\draw[->, thick] (rec) -- (cell);
\end{tikzpicture}""",
    "Immune Synapse": r"""\begin{tikzpicture}
\node[circle, draw, fill=red!15, minimum size=2cm] (tcell) at (-1.8,0) {T Cell};
\node[circle, draw, fill=orange!15, minimum size=2cm] (apc) at (1.8,0) {APC};
\draw[ultra thick, <->] (-0.8,0) -- (0.8,0) node[midway, above] {Synapse};
\end{tikzpicture}""",
    "CRISPR Workflow": r"""\begin{tikzpicture}
\node[rectangle, draw, fill=purple!15, minimum width=2cm, minimum height=0.8cm] (gRNA) at (0,1.5) {gRNA};
\node[rectangle, draw, fill=purple!25, minimum width=2cm, minimum height=0.8cm] (cas9) at (0,0) {Cas9};
\node[rectangle, draw, fill=gray!20, minimum width=2.5cm, minimum height=0.8cm] (dna) at (0,-1.5) {Target DNA};
\draw[->, thick] (gRNA) -- (cas9);
\draw[->, thick] (cas9) -- (dna);
\end{tikzpicture}""",
}


def convert_pdf_page_to_image(page: fitz.Page, dpi_scale: int, auto_crop: bool) -> Image.Image:
    Image.MAX_IMAGE_PIXELS = None
    mat = fitz.Matrix(dpi_scale, dpi_scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

    if auto_crop:
        bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox:
            img = img.crop(bbox)

    return img


def convert_pdf_bytes_to_images(pdf_bytes: bytes, dpi_scale: int, auto_crop: bool) -> list[Image.Image]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        images.append(convert_pdf_page_to_image(page=page, dpi_scale=dpi_scale, auto_crop=auto_crop))
    return images


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_zip(files: list[tuple[str, bytes]]) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, payload in files:
            zf.writestr(filename, payload)
    zip_buffer.seek(0)
    return zip_buffer.read()


def generate_cell_tikz(
    cell_label: str,
    cell_shape: str,
    cell_color: str,
    line_thickness: str,
    min_size: str,
    show_shadow: bool,
) -> str:
    # Prepare the label for LaTeX (handles newlines)
    label_to_print = cell_label.replace('\\n', '\\\\ ').replace('\n', '\\\\ ')

    # Logic for shadow
    shadow_part = ", drop shadow" if show_shadow else ""

    # Logic for shape
    shape_map = {
        "circle": "circle",
        "ellipse": "ellipse",
        "rectangle": "rectangle",
        "double circle": "circle, double, double distance=2pt",
    }
    final_shape = shape_map.get(cell_shape, "circle")

    return f"""\\begin{{tikzpicture}}
\\node [
    {final_shape},
    draw,
    fill=mycolor!20,
    {line_thickness},
    {min_size},
    inner sep=5pt,
    align=center{shadow_part}
] (mycell) at (0,0) {{{label_to_print}}};
\\end{{tikzpicture}}"""


def generate_tikz_code(
    cell_label: str,
    cell_color: str,
    shape_option: str,
    line_thickness: str,
    show_shadow: bool,
    preset: str,
) -> str:
    if preset == "Receptor":
        min_size = "minimum width=1.0cm, minimum height=0.4cm"
        final_shape = "rectangle"
    elif preset == "Nucleus":
        min_size = "minimum size=1.5cm"
        final_shape = "circle"
    else:
        min_size = "minimum size=2.5cm"
        final_shape = shape_option

    hex_color = cell_color.replace("#", "")
    tikz_body = generate_cell_tikz(
        cell_label=cell_label,
        cell_shape=final_shape,
        cell_color=cell_color,
        line_thickness=line_thickness,
        min_size=min_size,
        show_shadow=show_shadow,
    )
    return f"% Add this to your preamble:\n\\definecolor{{mycolor}}{{HTML}}{{{hex_color}}}\n\n{tikz_body}"


def generate_legend_tikz(legend_items: list[dict[str, str]]) -> str:
    lines = [r"\begin{tikzpicture}"]
    y = 0.0

    for item in legend_items:
        hex_color = item["color"].lstrip("#")
        label = item["label"]
        shape = item["shape"]
        style = item.get("style", "solid")

        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        # Lighten manually
        lighten_factor = 0.25
        r = int(r + (255 - r) * lighten_factor)
        g = int(g + (255 - g) * lighten_factor)
        b = int(b + (255 - b) * lighten_factor)

        tikz_color = f"{{rgb,255:red,{r};green,{g};blue,{b}}}"

        lines.append(
            f"\\node[{shape}, draw, {style}, fill={tikz_color}, minimum size=0.45cm] at (0,{round(y,2)}) {{}};"
        )
        lines.append(
            f"\\node[anchor=west] at (0.6,{round(y,2)}) {{{label}}};"
        )

        y -= 0.8

    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)




def build_full_tikz_document(tikz_body: str) -> str:
    return rf"""\documentclass[tikz,border=10pt]{{standalone}}
\usepackage[svgnames]{{xcolor}}
% Essential for AI-generated biological curves and precise positioning
\usetikzlibrary{{shadows,arrows.meta,positioning,shapes.geometric,calc}}
\begin{{document}}
{tikz_body}
\end{{document}}"""



def grayscale_score(img: Image.Image) -> float:
    gray = ImageOps.grayscale(img)
    hist = gray.histogram()
    total = sum(hist)
    if total == 0:
        return 0.0
    low = sum(hist[:32]) / total
    high = sum(hist[224:]) / total
    mid = sum(hist[96:160]) / total
    score = (high + low) * 100 - mid * 15
    return max(0.0, min(100.0, round(score, 2)))


def color_blind_preview(img: Image.Image) -> Image.Image:
    r, g, b = img.split()
    g_reduced = ImageEnhance.Brightness(g).enhance(0.35)
    return Image.merge("RGB", (r, g_reduced, b))


def compose_panel(
    images: list[Image.Image], columns: int, spacing: int, bg_color: str, add_labels: bool, label_color: str
) -> Image.Image:
    widths = [im.width for im in images]
    heights = [im.height for im in images]
    cell_w = max(widths)
    cell_h = max(heights)

    rows = (len(images) + columns - 1) // columns
    canvas_w = columns * cell_w + (columns + 1) * spacing
    canvas_h = rows * cell_h + (rows + 1) * spacing

    canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)
    draw = ImageDraw.Draw(canvas)

    for idx, img in enumerate(images):
        row = idx // columns
        col = idx % columns
        x = spacing + col * (cell_w + spacing)
        y = spacing + row * (cell_h + spacing)
        canvas.paste(img, (x, y))
        if add_labels:
            label = chr(65 + idx)
            draw.text((x + 10, y + 10), label, fill=label_color)

    return canvas


def build_project_payload(state: dict) -> str:
    return json.dumps(state, indent=2)


def load_project_payload(uploaded_project) -> dict:
    return json.loads(uploaded_project.read().decode("utf-8"))


RELATION_STYLES = {
    "Activation": {"arrow": "->", "style": "thick, ForestGreen", "legend": "Activation"},
    "Inhibition": {"arrow": "-|", "style": "thick, BrickRed", "legend": "Inhibition"},
    "Phosphorylation": {"arrow": "->", "style": "thick, RoyalBlue", "legend": "Phosphorylation (P)"},
    "Ubiquitination": {"arrow": "->", "style": "thick, Orange", "legend": "Ubiquitination (Ub)"},
    "Translocation": {"arrow": "->", "style": "dashed, thick, Purple", "legend": "Translocation"},
    "Cleavage": {"arrow": "->", "style": "densely dotted, thick, Gray", "legend": "Cleavage"},
}


def parse_csv_lines(raw_text: str) -> list[list[str]]:
    rows = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append([chunk.strip() for chunk in stripped.split(",")])
    return rows


def build_mechanistic_tikz(nodes: list[str], edges: list[dict], evidence_aware: bool = False, reviewer_mode: bool = False) -> str:
    if not nodes:
        return "% Add nodes first"

    lines = [r"\begin{tikzpicture}[node distance=2.4cm, every node/.style={font=\small}]", ""]
    x_pos = 0
    for idx, node in enumerate(nodes):
        lines.append(
            f"\\node[circle, draw, fill=blue!10, minimum size=1.5cm] ({node}) at ({x_pos},0) {{{node}}};"
        )
        x_pos += 3.0

    lines.append("")
    for edge in edges:
        relation = edge["relation"]
        style = RELATION_STYLES.get(relation, RELATION_STYLES["Activation"])
        evidence = edge.get("evidence", "hypothesis")
        tag = "[validated]" if evidence == "validated" else "[lit]" if evidence == "literature-supported" else "[hyp]"
        annotation = "P" if relation == "Phosphorylation" else "Ub" if relation == "Ubiquitination" else ""
        extra = ""
        if evidence_aware:
            evidence = edge.get("evidence", "hypothesis")
            if evidence == "validated":
                extra = ", line width=1.3pt"
            elif evidence == "literature-supported":
                extra = ", opacity=0.85"
            else:
                extra = ", opacity=0.5" if reviewer_mode else ", densely dashed"
        lines.append(
            f"\\draw[{style['style']}{extra}, {style['arrow']}] ({edge['source']}) -- ({edge['target']}) node[midway, above] {{{tag} {annotation}}};"
        )

    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)


def ontology_validate_edges(edges: list[dict]) -> list[str]:
    warnings = []
    for edge in edges:
        src = edge["source"].lower()
        dst = edge["target"].lower()
        relation = edge["relation"]

        if "receptor" in src and "nucleus" in dst and relation != "Translocation":
            warnings.append(f"{edge['source']} -> {edge['target']}: add a translocation step before nuclear entry.")

        if relation == "Phosphorylation" and "dna" in dst:
            warnings.append(f"{edge['source']} -> {edge['target']}: phosphorylation usually targets proteins, not DNA.")

        if edge.get("evidence") == "hypothesis":
            warnings.append(f"{edge['source']} -> {edge['target']}: mark references for hypothesis-only edges.")

    return warnings


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def contrast_score(hex_a: str, hex_b: str) -> float:
    r1, g1, b1 = hex_to_rgb(hex_a)
    r2, g2, b2 = hex_to_rgb(hex_b)
    return round((abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)) / 7.65, 2)


def submission_readiness_score(fonts: int, line_styles: int, palette: list[str], target_dpi: int) -> tuple[float, list[str]]:
    checks = []
    score = 100.0

    if fonts > 2:
        score -= 12
        checks.append("Reduce font families to <=2 for consistency.")
    if line_styles > 3:
        score -= 10
        checks.append("Use <=3 line styles to reduce cognitive load.")
    if target_dpi < 300:
        score -= 20
        checks.append("Increase export DPI to at least 300 for journals.")

    if len(palette) >= 2:
        min_contrast = min(contrast_score(palette[i], palette[i + 1]) for i in range(len(palette) - 1))
        if min_contrast < 35:
            score -= 18
            checks.append("Increase contrast between adjacent palette colors.")

    if not checks:
        checks.append("Looks publication-ready. Validate panel labels at print scale.")

    return max(0.0, round(score, 2)), checks


def ai_scene_from_prompt(prompt: str) -> tuple[list[str], list[dict], list[str]]:
    p = prompt.lower()
    nodes = ["Ligand", "Receptor", "MAPK", "Nucleus"]
    edges = [
        {"source": "Ligand", "target": "Receptor", "relation": "Activation", "evidence": "hypothesis"},
        {"source": "Receptor", "target": "MAPK", "relation": "Activation", "evidence": "hypothesis"},
        {"source": "MAPK", "target": "Nucleus", "relation": "Translocation", "evidence": "hypothesis"},
    ]
    assumptions = ["Generated with heuristic prompt parsing.", "Please validate every edge with literature."]

    if "pd-1" in p or "inhibitory" in p:
        nodes.append("PD-1")
        edges.append({"source": "PD-1", "target": "Receptor", "relation": "Inhibition", "evidence": "hypothesis"})
    if "phosph" in p:
        edges.append({"source": "Receptor", "target": "MAPK", "relation": "Phosphorylation", "evidence": "hypothesis"})
    if "crispr" in p:
        nodes = ["gRNA", "Cas9", "TargetDNA"]
        edges = [
            {"source": "gRNA", "target": "Cas9", "relation": "Activation", "evidence": "hypothesis"},
            {"source": "Cas9", "target": "TargetDNA", "relation": "Cleavage", "evidence": "hypothesis"},
        ]
        assumptions.append("CRISPR template chosen due to prompt keyword.")

    return nodes, edges, assumptions


def build_time_series_tikz(states: list[str]) -> str:
    lines = [r"\begin{tikzpicture}[>=Stealth, node distance=2.8cm]", ""]
    x = 0
    for idx, state in enumerate(states):
        node_name = f"s{idx}"
        lines.append(f"\\node[rectangle, draw, rounded corners, fill=teal!10, minimum width=2.7cm, minimum height=0.9cm] ({node_name}) at ({x},0) {{{state}}};")
        if idx > 0:
            lines.append(f"\\draw[->, thick] (s{idx-1}) -- ({node_name});")
        x += 3.6
    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)


def organelle_tikz(organelle: str, intensity: int, variant: str) -> str:
    if organelle == "Mitochondria":
        return rf"""\begin{{tikzpicture}}
\draw[thick] (0,0) ellipse (3 and 1.5);
\foreach \x in {{-{intensity/12:.2f},0,{intensity/12:.2f}}} {{
  \draw[thick] (-2.2+\x,0) .. controls (-1.7,0.6) and (-0.8,0.6) .. (-0.3,0)
  .. controls (0.2,-0.6) and (1.1,-0.6) .. (1.8,0);
}}
\node at (0,-2) {{{variant}}};
\end{{tikzpicture}}"""
    if organelle == "Golgi":
        return rf"""\begin{{tikzpicture}}
\foreach \i in {{0,...,4}} {{
  \draw[thick] (-2+0.25*\i,0.35*\i) to[out=15,in=165] (2-0.25*\i,0.35*\i);
}}
\node at (0,-0.8) {{{variant}}};
\end{{tikzpicture}}"""
    if organelle == "Lipid Bilayer":
        return rf"""\begin{{tikzpicture}}
\foreach \x in {{-3,-2.5,...,3}} {{
  \draw[fill=blue!30] (\x,0.5) circle (0.1);
  \draw[fill=blue!30] (\x,-0.5) circle (0.1);
  \draw[thick] (\x,0.4) -- (\x,-0.4);
}}
\node[draw, fill=orange!20] at (0,0) {{Protein x{max(1, intensity//20)}}};
\node at (0,-1.2) {{{variant}}};
\end{{tikzpicture}}"""
    return rf"""\begin{{tikzpicture}}
\draw[thick] (0,0) circle (1.6);
\draw[dashed] (0,0) circle ({0.6 + intensity/100:.2f});
\node at (0,-2) {{{variant}}};
\end{{tikzpicture}}"""


def collaboration_report(comment_rows: list[list[str]]) -> str:
    lines = ["# Collaboration Review", ""]
    approvals = 0
    for row in comment_rows:
        if len(row) < 4:
            continue
        reviewer, node, status, note = row[0], row[1], row[2], row[3]
        if status.lower() == "approve":
            approvals += 1
        lines.append(f"- **{reviewer}** on `{node}` | {status.upper()}: {note}")
    lines.append("")
    lines.append(f"Approved items: {approvals}")
    return "\n".join(lines)


def build_chemfig_document(chemfig_code: str, caption: str) -> str:
    lines = [
        r"\documentclass[tikz,border=10pt]{standalone}",
        r"\usepackage{chemfig}",
        r"\usepackage[version=4]{mhchem}",
        r"\begin{document}",
        r"\begin{tikzpicture}",
        rf"\node[anchor=west] at (0,0) {{\Large {caption}}};",
        rf"\node[anchor=west] at (0,-1.0) {{\chemfig{{{chemfig_code}}}}};",
        r"\end{tikzpicture}",
        r"\end{document}",
    ]
    return "\n".join(lines)


def build_significance_tikz(x1: float, x2: float, y: float, stars: str, plot_type: str = "bar") -> str:
    baseline = "0" if plot_type == "bar" else str(round(y - 1.2, 2))
    return rf"""\begin{{tikzpicture}}
\draw[->] (0,{baseline}) -- (0,{y + 1.5}) node[above] {{Value}};
\draw[->] (0,{baseline}) -- ({max(x1, x2) + 1.2},{baseline}) node[right] {{Condition}};
\draw[thick, fill=blue!20] ({x1 - 0.25},{baseline}) rectangle ({x1 + 0.25},{y - 0.2});
\draw[thick, fill=green!20] ({x2 - 0.25},{baseline}) rectangle ({x2 + 0.25},{y});
\draw[stealth-stealth] ({x1},{y + 0.2}) -- node[above]{{{stars}}} ({x2},{y + 0.2});
\end{{tikzpicture}}"""


def build_stat_annotation_overlay_tikz(
    image_filename: str,
    panel_label: str,
    brackets: list[dict[str, float | str]],
    image_width_cm: float,
    image_height_cm: float,
) -> str:
    lines = [
        r"\documentclass[tikz,border=2pt]{standalone}",
        r"\usepackage{graphicx}",
        r"\usepackage{tikz}",
        r"\begin{document}",
        r"\begin{tikzpicture}",
        rf"\node[anchor=south west, inner sep=0] (img) at (0,0) {{\includegraphics[width={image_width_cm}cm,height={image_height_cm}cm]{{{image_filename}}}}};",
        rf"\node[anchor=north west, font=\bfseries\fontsize{{18}}{{18}}\selectfont] at (0,{image_height_cm}) {{{panel_label}}};",
    ]

    for bracket in brackets:
        x1 = bracket["x1"]
        x2 = bracket["x2"]
        y = bracket["y"]
        rise = bracket["rise"]
        stars = bracket["stars"]
        lines.append(
            rf"\draw[thick] ({x1},{y}) -- ({x1},{y + rise}) -- ({x2},{y + rise}) -- ({x2},{y}) node[midway, above] {{{stars}}};"
        )

    lines.extend([r"\end{tikzpicture}", r"\end{document}"])
    return "\n".join(lines)


def build_histogram_overlay_tikz(x_steps: int, y_steps: int, title: str) -> str:
    lines = [r"\begin{tikzpicture}[x=0.65cm,y=0.45cm]", f"\node[anchor=west] at (0,{y_steps+1}) {{{title}}};"]
    lines.append(r"\draw[->] (0,0) -- (" + str(x_steps + 0.7) + r",0) node[right] {Intensity};")
    lines.append(r"\draw[->] (0,0) -- (0," + str(y_steps + 0.7) + r") node[above] {Counts};")
    for x in range(1, x_steps + 1):
        lines.append(f"\draw[gray!30] ({x},0) -- ({x},{y_steps});")
    for y in range(1, y_steps + 1):
        lines.append(f"\draw[gray!30] (0,{y}) -- ({x_steps},{y});")
    lines.append(r"\draw[thick, RoyalBlue, smooth] plot coordinates {(0.3,0.5) (1.0,1.3) (2.0,2.5) (3.0,3.2) (4.3,2.2) (5.5,1.4)};")
    lines.append(r"\draw[thick, BrickRed, smooth] plot coordinates {(0.5,0.3) (1.5,1.0) (2.5,1.8) (3.6,2.8) (4.7,3.0) (5.8,2.2)};")
    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)


def build_panel_layout_tikz(layout: str, spacing: float, show_labels: bool) -> str:
    if layout == "2x2":
        coords = [(0,2), (4+spacing,2), (0,0), (4+spacing,0)]
        labels = ["A", "B", "C", "D"]
    else:
        coords = [(0,2), (4+spacing,2), (8+2*spacing,2), (0,0), (4+spacing,0), (8+2*spacing,0)]
        labels = ["A", "B", "C", "D", "E", "F"]

    lines = [r"\begin{tikzpicture}[x=1cm,y=1cm]", r"\def\w{3.7}", r"\def\h{1.7}"]
    for idx, (x, y) in enumerate(coords):
        lines.append(f"\draw[thick] ({x},{y}) rectangle ++(\w,\h);")
        if show_labels:
            lines.append(f"\node[anchor=north west, font=\bfseries] at ({x+0.12},{y+1.58}) {{{labels[idx]}}};")
    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)


def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value.strip())
    except Exception:
        return default


def parse_matrix_text(raw: str, rows: int, cols: int, default: float = 0.0) -> list[list[float]]:
    parsed = []
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    for r in range(rows):
        vals = [v.strip() for v in lines[r].split(',')] if r < len(lines) else []
        parsed.append([_safe_float(vals[c], default) if c < len(vals) else default for c in range(cols)])
    return parsed


def generate_grouped_bar_plot_image(categories: list[str], groups: list[str], values: list[list[float]], errors: list[list[float]], width: int = 1200, height: int = 800) -> Image.Image:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    ml, mr, mt, mb = 110, 60, 60, 120
    pw, ph = width - ml - mr, height - mt - mb
    max_y = max(1.0, max(values[g][c] + errors[g][c] for g in range(len(groups)) for c in range(len(categories)))) * 1.15

    draw.line((ml, mt + ph, ml + pw, mt + ph), fill="black", width=3)
    draw.line((ml, mt, ml, mt + ph), fill="black", width=3)

    for i in range(6):
        yv = max_y * i / 5
        y = mt + ph - (yv / max_y) * ph
        draw.line((ml - 8, y, ml, y), fill="black", width=2)
        draw.text((15, y - 8), f"{yv:.1f}", fill="black")

    palette = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2"]
    cat_span = pw / max(1, len(categories))
    bar_w = min(38, (cat_span * 0.7) / max(1, len(groups)))

    for c_idx, cat in enumerate(categories):
        cat_x0 = ml + c_idx * cat_span + cat_span * 0.15
        for g_idx, grp in enumerate(groups):
            val = values[g_idx][c_idx]
            err = errors[g_idx][c_idx]
            x0 = cat_x0 + g_idx * bar_w
            x1 = x0 + bar_w * 0.85
            y1 = mt + ph
            y0 = y1 - (val / max_y) * ph
            draw.rectangle((x0, y0, x1, y1), fill=palette[g_idx % len(palette)], outline="black", width=1)
            if err > 0:
                ey = (err / max_y) * ph
                cx = (x0 + x1) / 2
                draw.line((cx, y0 - ey, cx, y0), fill="black", width=2)
                draw.line((cx - 7, y0 - ey, cx + 7, y0 - ey), fill="black", width=2)
        draw.text((cat_x0, mt + ph + 15), cat, fill="black")

    for g_idx, grp in enumerate(groups):
        lx, ly = ml + g_idx * 190, height - 40
        col = palette[g_idx % len(palette)]
        draw.rectangle((lx, ly, lx + 24, ly + 18), fill=col, outline="black")
        draw.text((lx + 32, ly + 1), grp, fill="black")
    return img


def grouped_bar_pgfplots(categories: list[str], groups: list[str], values: list[list[float]], errors: list[list[float]]) -> str:
    lines = [r"\begin{tikzpicture}", r"\begin{axis}[ybar,bar width=12pt,width=13cm,height=8cm,legend style={at={(0.5,-0.15)},anchor=north,legend columns=-1},symbolic x coords={" + ",".join(categories) + r"},xtick=data,ymajorgrids=true]"]
    for g_idx, grp in enumerate(groups):
        coords = " ".join([f"({categories[c_idx]},{values[g_idx][c_idx]}) +- (0,{errors[g_idx][c_idx]})" for c_idx in range(len(categories))])
        lines.append(rf"\addplot+[error bars/.cd,y dir=both,y explicit] coordinates {{{coords}}};")
        lines.append(rf"\addlegendentry{{{grp}}}")
    lines.extend([r"\end{axis}", r"\end{tikzpicture}"])
    return "\n".join(lines)


def fit_4pl_grid(concentrations: list[float], responses: list[float]) -> dict[str, float]:
    min_x, max_x = min(concentrations), max(concentrations)
    min_y, max_y = min(responses), max(responses)
    best = {"mse": float("inf"), "bottom": min_y, "top": max_y, "ec50": (min_x + max_x) / 2, "hill": 1.0}
    for b in [min_y - 10, min_y - 5, min_y, min_y + 5]:
        for t in [max_y - 5, max_y, max_y + 5, max_y + 10]:
            if t <= b:
                continue
            for e in [min_x + (max_x - min_x) * f for f in [0.15, 0.3, 0.5, 0.7, 0.85]]:
                e = max(1e-8, e)
                for h in [0.6, 0.8, 1.0, 1.3, 1.6, 2.0]:
                    preds = [b + (t - b) / (1 + (x / e) ** h) for x in concentrations]
                    mse = sum((preds[i] - responses[i]) ** 2 for i in range(len(responses))) / len(responses)
                    if mse < best["mse"]:
                        best = {"mse": mse, "bottom": b, "top": t, "ec50": e, "hill": h}
    return best


def generate_dose_response_image(concentrations: list[float], responses: list[float], fit: dict[str, float], width: int = 1200, height: int = 800) -> Image.Image:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    ml, mr, mt, mb = 120, 60, 50, 90
    pw, ph = width - ml - mr, height - mt - mb
    min_x, max_x = min(concentrations), max(concentrations)
    min_y, max_y = min(min(responses), fit["bottom"]), max(max(responses), fit["top"])
    pad = (max_y - min_y) * 0.15 + 1
    min_y -= pad
    max_y += pad

    sx = lambda x: ml + ((x - min_x) / max(1e-9, max_x - min_x)) * pw
    sy = lambda y: mt + ph - ((y - min_y) / max(1e-9, max_y - min_y)) * ph

    draw.line((ml, mt + ph, ml + pw, mt + ph), fill="black", width=3)
    draw.line((ml, mt, ml, mt + ph), fill="black", width=3)

    for x, y in zip(concentrations, responses):
        px, py = sx(x), sy(y)
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill="#1f77b4", outline="black")

    curve = []
    for i in range(250):
        x = min_x + (max_x - min_x) * i / 249
        y = fit["bottom"] + (fit["top"] - fit["bottom"]) / (1 + (x / fit["ec50"]) ** fit["hill"])
        curve.append((sx(x), sy(y)))
    draw.line(curve, fill="#d62728", width=3)
    draw.line((sx(fit["ec50"]), sy(min_y), sx(fit["ec50"]), sy(max_y)), fill="#555555", width=2)
    draw.text((sx(fit["ec50"]) + 5, sy((fit["bottom"] + fit["top"]) / 2) - 20), f"IC50≈{fit['ec50']:.3g}", fill="black")
    return img


def dose_response_pgfplots(concentrations: list[float], responses: list[float], fit: dict[str, float]) -> str:
    pts = " ".join([f"({concentrations[i]},{responses[i]})" for i in range(len(concentrations))])
    lines = [r"\begin{tikzpicture}", r"\begin{semilogxaxis}[width=13cm,height=8cm,xlabel={Concentration},ylabel={% Response},grid=major]", rf"\addplot+[only marks] coordinates {{{pts}}};", rf"\addplot+[domain={min(concentrations)}:{max(concentrations)},samples=120] {{{fit['bottom']} + ({fit['top']}-{fit['bottom']})/(1+(x/{fit['ec50']})^{fit['hill']})}};", rf"\addplot[dashed] coordinates {{({fit['ec50']},{min(responses)-10}) ({fit['ec50']},{max(responses)+10})}};", r"\end{semilogxaxis}", r"\end{tikzpicture}"]
    return "\n".join(lines)




def ontology_autofix(nodes: list[str], edges: list[dict]) -> tuple[list[str], list[dict], list[str]]:
    fixed_nodes = list(nodes)
    fixed_edges: list[dict] = []
    actions: list[str] = []

    for edge in edges:
        src = edge.get("source", "")
        dst = edge.get("target", "")
        relation = edge.get("relation", "Activation")

        if "receptor" in src.lower() and "nucleus" in dst.lower() and relation != "Translocation":
            if "Cytosol" not in fixed_nodes:
                fixed_nodes.append("Cytosol")
            fixed_edges.append({"source": src, "target": "Cytosol", "relation": "Translocation", "evidence": edge.get("evidence", "hypothesis")})
            fixed_edges.append({"source": "Cytosol", "target": dst, "relation": relation, "evidence": edge.get("evidence", "hypothesis")})
            actions.append(f"Inserted translocation bridge: {src} -> Cytosol -> {dst}.")
            continue

        if relation == "Phosphorylation" and "dna" in dst.lower():
            fixed_edge = dict(edge)
            fixed_edge["relation"] = "Activation"
            fixed_edges.append(fixed_edge)
            actions.append(f"Adjusted relation for {src}->{dst}: Phosphorylation replaced with Activation.")
            continue

        fixed_edges.append(dict(edge))

    if not actions:
        actions.append("No ontology autofixes were required.")

    return fixed_nodes, fixed_edges, actions


def journal_compliance_lint(font_pt: float, line_styles: int, palette: list[str], target_dpi: int, panel_labels_ok: bool) -> tuple[float, list[str]]:
    score = 100.0
    issues: list[str] = []

    if font_pt < 7:
        score -= 20
        issues.append("Increase minimum font size to >= 7 pt for print readability.")
    if line_styles > 3:
        score -= 10
        issues.append("Reduce distinct line styles to <= 3.")
    if target_dpi < 300:
        score -= 20
        issues.append("Export at >=300 DPI for manuscript quality.")
    if not panel_labels_ok:
        score -= 15
        issues.append("Panel labels should be present and consistently positioned.")

    if len(palette) >= 2:
        min_contrast = min(contrast_score(palette[i], palette[i + 1]) for i in range(len(palette) - 1))
        if min_contrast < 35:
            score -= 15
            issues.append("Palette contrast is low; increase separation between neighboring colors.")

    if not issues:
        issues.append("All major journal checks passed.")

    return max(0.0, round(score, 2)), issues


def parse_tikz_roundtrip(tikz_text: str) -> tuple[list[str], list[dict], list[str]]:
    node_matches = re.findall(r"\\node\[[^\]]*\]\s*\(([^)]+)\).*?\{([^}]*)\};", tikz_text)
    nodes = [label.strip() or name.strip() for name, label in node_matches]
    edge_matches = re.findall(r"\\draw\[[^\]]*\]\s*\(([^)]+)\)\s*--\s*\(([^)]+)\)", tikz_text)
    edges = [{"source": a.strip(), "target": b.strip(), "relation": "Activation", "evidence": "hypothesis"} for a, b in edge_matches]
    notes = [f"Parsed {len(nodes)} node(s) and {len(edges)} edge(s)."]
    return nodes, edges, notes


def generate_template_family(organelle: str, variant_labels: list[str], intensity: int) -> dict[str, str]:
    return {label: organelle_tikz(organelle, intensity, label) for label in variant_labels}


def auto_significance_brackets(group_labels: list[str], values: list[float]) -> list[dict[str, float | str]]:
    brackets: list[dict[str, float | str]] = []
    if len(values) < 2:
        return brackets
    max_val = max(values) if values else 1.0
    for i in range(len(values) - 1):
        diff = abs(values[i + 1] - values[i])
        stars = "ns"
        if diff >= 0.45 * max_val:
            stars = "***"
        elif diff >= 0.25 * max_val:
            stars = "**"
        elif diff >= 0.12 * max_val:
            stars = "*"
        brackets.append({"x1": float(i + 1), "x2": float(i + 2), "y": float(max(values) + (i + 1) * 0.4), "rise": 0.25, "stars": stars})
    return brackets


def build_provenance_manifest(files: list[tuple[str, bytes]], params: dict) -> str:
    payload = {
        "generated_at": datetime.now().isoformat(),
        "app": "Bio-TikZ Studio",
        "parameters": params,
        "artifacts": [],
    }
    for name, content in files:
        payload["artifacts"].append({
            "filename": name,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    return json.dumps(payload, indent=2)


def collaboration_graph(comment_rows: list[list[str]]) -> dict:
    summary = {"approved": 0, "changes": 0, "rejected": 0, "by_node": {}}
    for row in comment_rows:
        if len(row) < 4:
            continue
        reviewer, node, status, note = row[0], row[1], row[2].lower(), row[3]
        if status.startswith("approve"):
            summary["approved"] += 1
        elif status.startswith("change"):
            summary["changes"] += 1
        else:
            summary["rejected"] += 1
        summary["by_node"].setdefault(node, []).append({"reviewer": reviewer, "status": status, "note": note})
    return summary


def accessibility_copilot_v2(img: Image.Image) -> dict:
    gray = ImageOps.grayscale(img)
    hist = gray.histogram()
    dark = sum(hist[:48])
    bright = sum(hist[208:])
    total = max(1, sum(hist))
    balance = round((min(dark, bright) / total) * 200, 2)
    score = grayscale_score(img)
    suggestion = "Increase local contrast around labels." if balance < 12 else "Contrast distribution looks balanced."
    return {"score": score, "contrast_balance": balance, "suggestion": suggestion}


def build_storyboard_markdown(mechanism_title: str, states: list[str], panels: list[str], quant_summary: str) -> str:
    state_txt = " -> ".join(states) if states else "N/A"
    panel_txt = "\n".join([f"- {p}" for p in panels]) if panels else "- None"
    return f"""# Figure Storyboard

## Mechanism
{mechanism_title}

## State Progression
{state_txt}

## Panels
{panel_txt}

## Quant Summary
{quant_summary}
"""


def domain_packs_catalog() -> dict[str, dict]:
    return {
        "Immunology": {"templates": ["Immune Synapse", "Cell Signaling"], "relations": ["Activation", "Inhibition", "Translocation"]},
        "Oncology": {"templates": ["CRISPR Workflow", "Cell Signaling"], "relations": ["Activation", "Phosphorylation", "Ubiquitination"]},
        "Metabolism": {"templates": ["Mitochondria (Bezier)", "Lipid Bilayer"], "relations": ["Activation", "Translocation", "Cleavage"]},
    }


def diff_projects(old_payload: str, new_payload: str) -> str:
    old_lines = old_payload.splitlines()
    new_lines = new_payload.splitlines()
    return "\n".join(difflib.unified_diff(old_lines, new_lines, fromfile="previous", tofile="current", lineterm=""))

def reaction_scheme_template(title: str, step1: str, step2: str, conditions: str) -> str:
    return rf"""\begin{{tikzpicture}}[>=Stealth]
\node[draw, rounded corners, minimum width=3.2cm, minimum height=1.2cm] (a) at (0,0) {{{step1}}};
\node[draw, rounded corners, minimum width=3.2cm, minimum height=1.2cm] (b) at (7,0) {{{step2}}};
\draw[->, thick] (a) -- node[above] {{{conditions}}} (b);
\node[anchor=west, font=\bfseries] at (-1.2,1.8) {{{title}}};
\node[draw, dashed, minimum width=2.2cm, minimum height=0.8cm] at (3.5,-1.3) {{Label/18F}};
\end{{tikzpicture}}"""


st.title("🔬 Bio-TikZ Studio | End-to-End Figure Production")
st.caption("Phase 1 + 2 + 3 features: conversion, design, accessibility, composition, packaging, and workflow automation")
st.markdown("---")

main_tabs = st.tabs(
    [
        "🖼️ Image Lab",
        "🧬 Design Studio",
        "📊 Data & Plots",
        "🧠 AI & Logic",
        "📋 Project Management",
    ]
)

with main_tabs[0]:
    st.header("Batch PDF Converter + Journal Presets")

    preset = st.selectbox("Output Profile", list(OUTPUT_PROFILES.keys()))
    default_profile = OUTPUT_PROFILES[preset]

    c1, c2, c3 = st.columns(3)
    with c1:
        # 1. Update slider to float for finer control
        dpi_scale = st.slider("Resolution Scale (1.0 = 72 DPI)", 1.0, 12.0, float(default_profile["dpi_scale"]), step=0.5)

        # 2. Calculate the actual DPI (PDF base is 72)
        calculated_dpi = int(dpi_scale * 72)

        # 3. Add the Validation Logic (Visual Feedback)
        if calculated_dpi >= 300:
            st.success(f"✅ **{calculated_dpi} DPI**: Journal Quality")
        elif calculated_dpi >= 150:
            st.info(f"💡 **{calculated_dpi} DPI**: Standard Web Quality")
        else:
            st.warning(f"⚠️ **{calculated_dpi} DPI**: Low Resolution (Draft)")

    with c2:
        auto_crop = st.checkbox("Auto-Crop White Margins", value=default_profile["auto_crop"])
    with c3:
        batch_mode = st.checkbox("Enable Batch ZIP Export", value=True)

    uploaded_pdfs = st.file_uploader(
        "Upload one or many PDF figures", type=["pdf"], accept_multiple_files=True
    )

    if uploaded_pdfs:
        zip_entries: list[tuple[str, bytes]] = []
        st.subheader(f"Processed Pages (@ {calculated_dpi} DPI)")

        for pdf in uploaded_pdfs:
            pdf_images = convert_pdf_bytes_to_images(pdf.read(), dpi_scale=dpi_scale, auto_crop=auto_crop)
            pdf_stem = Path(pdf.name).stem
            st.markdown(f"**{pdf.name}**")

            for page_idx, page_img in enumerate(pdf_images, start=1):
                st.image(page_img, caption=f"{pdf_stem} | Page {page_idx}", use_container_width=True)
                filename = f"{pdf_stem}_{calculated_dpi}DPI_Page{page_idx}.png"
                png_bytes = image_to_png_bytes(page_img)
                st.download_button(
                    label=f"Download {filename}",
                    data=png_bytes,
                    file_name=filename,
                    mime="image/png",
                    key=f"single_{pdf_stem}_{page_idx}",
                )
                zip_entries.append((filename, png_bytes))

        if batch_mode and zip_entries:
            zip_blob = build_zip(zip_entries)
            st.download_button(
                "⬇️ Download Complete Batch (ZIP)",
                data=zip_blob,
                file_name=f"bio_tikz_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                mime="application/zip",
            )

with main_tabs[1]:
    st.header("TikZ Generator + Template Gallery + Legend Generator")
    st.write("Generate clean code for biological nodes to paste into Overleaf.")

    template_choice = st.selectbox("Template Gallery", ["Custom Node"] + list(TIKZ_TEMPLATES.keys()))

    if template_choice != "Custom Node":
        st.subheader("Template Preview Code")
        st.code(TIKZ_TEMPLATES[template_choice], language="latex")

    c1, c2, c3 = st.columns(3)
    with c1:
        cell_label = st.text_input("Cell Label", "Macrophage")
        cell_color = st.color_picker("Cell Color", "#e74c3c")
    with c2:
        shape_option = st.selectbox("Shape", ["circle", "ellipse", "rectangle", "double circle"])
        line_thickness = st.select_slider("Line Thickness", ["thin", "thick", "ultra thick"], value="thick")
    with c3:
        show_shadow = st.checkbox("Add Shadow", value=True)
        preset = st.selectbox("Style Preset", ["Standard Cell", "Receptor", "Nucleus"])

    tikz_code = generate_tikz_code(
        cell_label=cell_label,
        cell_color=cell_color,
        shape_option=shape_option,
        line_thickness=line_thickness,
        show_shadow=show_shadow,
        preset=preset,
    )
    full_doc_mode = st.toggle("Generate full .tex document", value=False)
    current_hex = cell_color.replace("#", "")
    
    clean_tikz = tikz_code.split("\n\n")[-1] if "% Add this" in tikz_code else tikz_code

    if full_doc_mode:
        final_output = f"""\\documentclass[tikz,border=10pt]{{standalone}}
\\usetikzlibrary{{shapes.geometric, shadows}}
\\usepackage{{xcolor}}

\\definecolor{{mycolor}}{{HTML}}{{{current_hex}}}

\\begin{{document}}

{clean_tikz}

\\end{{document}}"""
    else:
        final_output = f"% Add this to your preamble:\n\\definecolor{{mycolor}}{{HTML}}{{{current_hex}}}\n\n{clean_tikz}"

    st.subheader("Generated Node Code")
    st.code(final_output, language="latex")
    st.download_button(
        label="Download .tex file",
        data=final_output,
        file_name="cell_diagram.tex",
        mime="text/x-tex",
     )
    
    st.markdown("### Smart Legend Generator")
    # --- PRESET LOGIC START ---
    col_pre1, col_pre2 = st.columns([1, 2])
    with col_pre1:
        if st.button("🧬 Load Immunometabolism Preset"):
            st.session_state.preset_labels = ["DAPI (Nucleus)", "CD8+ T-Cell", "Glucose Flux", "Mitochondria"]
            st.session_state.preset_colors = ["#0000FF", "#FF0000", "#00FF00", "#FFA500"]
            st.rerun()
    # --- PRESET LOGIC END ---

    n_items = st.slider("Number of legend items", 2, 8, 4)
    legend_items = []
    for i in range(n_items):
        l1, l2, l3, l4 = st.columns(4)
        with l1:
            # 1. Define the presets variable first
            preset_labels = st.session_state.get("preset_labels", [])
            default_label = preset_labels[i] if i < len(preset_labels) else f"Entity {i+1}"

            
           
            
                
            
                
            label = st.text_input(f"Label {i+1}", default_label, key=f"lab_{i}")
        with l2:
            # Check if a preset color exists, otherwise use default blue
            preset_colors = st.session_state.get("preset_colors", [])
            default_color = preset_colors[i] if i < len(preset_colors) else "#3498db"
            color = st.color_picker(f"Color {i+1}", default_color, key=f"col_{i}")
        with l3:
            shape = st.selectbox(f"Shape {i+1}", ["circle", "rectangle", "ellipse"], key=f"shp_{i}")
        with l4:
            l_style = st.selectbox(f"Style {i+1}", ["solid", "dashed", "dotted", "double"], key=f"sty_{i}")

        legend_items.append({"label": label, "color": color, "shape": shape, "style": l_style})

        # This replaces your current line 427 and 428
        st.markdown("### 📍 Generated Legend")
    
    # 1. Get the raw TikZ body
    legend_body = generate_legend_tikz(legend_items)
    
    # 2. Add the Toggle (same as your first image)
    full_doc_legend = st.toggle("Generate full .tex document for legend", value=False, key="legend_toggle")

    if full_doc_legend:
        # Wrap in full standalone document
        final_legend_output = rf"""\documentclass[tikz,border=10pt]{{standalone}}
\usepackage[svgnames]{{xcolor}}
\usetikzlibrary{{shapes.geometric, positioning}}

\begin{{document}}

{legend_body}

\end{{document}}"""
    else:
        # Just the TikZ snippet
        final_legend_output = legend_body

    # 3. Display the code
    st.code(final_legend_output, language="latex")
    
    # 4. Add Download Button
    st.download_button(
        label="Download Legend .tex file",
        data=final_legend_output,
        file_name="bio_legend.tex",
        mime="text/x-tex",
    )

        # 5. Keep the expander below for quick help
    with st.expander("🚀 How to use this in Overleaf / LaTeX"):
        st.markdown("**Step 1:** Copy this preamble to the very top of your LaTeX file:")
        
        st.code(r"""\documentclass{article}
\usepackage[svgnames]{xcolor}
\usepackage{tikz}
\usetikzlibrary{shapes.geometric, arrows.meta, shadows, positioning}

\begin{document}""", language="latex")
        
        st.markdown(r"""
**Option A:** If you downloaded the full .tex, simply upload it to Overleaf.
**Option B:** If copying the snippet, ensure your preamble has `\usepackage[svgnames]{xcolor}`.
""")
        
        st.info("💡 Tip: If you want the colors to be darker, change `!25` to `!100` in the code.")

    # Your line 429 (AI Importer) continues below this...

            # --- AI IMPORTER SECTION ---
    st.markdown("---")
    st.subheader("🤖 AI-Snippet Importer")
    st.info("Paste TikZ code (like your Mitochondria example) below. We will wrap it in a publication-ready preamble.")
    
    ai_raw_code = st.text_area(
        "Paste Raw TikZ Code here:", 
        placeholder=r"\begin{tikzpicture} ... \end{tikzpicture}", 
        height=250,
        key="ai_importer_unique"
    )
    
    if ai_raw_code:
        # STEP 1: Clean the input
        clean_ai_body = ai_raw_code
        if r"\begin{document}" in ai_raw_code:
            clean_ai_body = ai_raw_code.split(r"\begin{document}")[-1].split(r"\end{document}")[0]
    
        # --- NEW LOGIC START: Ensure tikzpicture environment exists ---
        if r"\begin{tikzpicture}" not in clean_ai_body:
            processed_body = f"\\begin{{tikzpicture}}\n{clean_ai_body}\n\\end{{tikzpicture}}"
        else:
            processed_body = clean_ai_body
        # --- NEW LOGIC END ---
    
        # STEP 2: Wrap in the professional preamble
        # Pass 'processed_body' instead of 'clean_ai_body'
        ai_final_output = build_full_tikz_document(processed_body)
    
        st.markdown("#### ✨ Enhanced Publication-Ready Code")
        st.code(ai_final_output, language="latex")
            
        # STEP 3: Export
        st.download_button(
            label="Download AI-Enhanced .tex",
            data=ai_final_output,
            file_name="ai_generated_figure.tex",
            mime="text/x-tex",
            key="ai_download_unique"
        )

    # --- END OF AI IMPORTER ---



with main_tabs[0]:
    st.header("Accessibility Validator + Reviewer-Ready Export")
    uploaded_image = st.file_uploader("Upload PNG/JPG for accessibility check", type=["png", "jpg", "jpeg"])

    if uploaded_image is not None:
        Image.MAX_IMAGE_PIXELS = None
        base_img = Image.open(uploaded_image).convert("RGB")
        gray_img = ImageOps.grayscale(base_img)
        cb_img = color_blind_preview(base_img)

        score = grayscale_score(base_img)
        st.metric("Grayscale Resilience Score", f"{score}/100")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.image(base_img, caption="Original", use_container_width=True)
        with c2:
            st.image(gray_img, caption="Grayscale Preview", use_container_width=True)
        with c3:
            st.image(cb_img, caption="Color-Blind Approximation", use_container_width=True)

        reviewer_files = [
            ("figure_original.png", image_to_png_bytes(base_img)),
            ("figure_grayscale.png", image_to_png_bytes(gray_img.convert("RGB"))),
            ("figure_colorblind_preview.png", image_to_png_bytes(cb_img)),
            (
                "reviewer_notes.md",
                (
                    "# Reviewer Export Notes\n"
                    f"- Grayscale resilience score: {score}/100\n"
                    "- Included original, grayscale, and color-blind preview exports.\n"
                    "- Suggested check: verify labels remain legible at print scale.\n"
                ).encode("utf-8"),
            ),
        ]
        reviewer_zip = build_zip(reviewer_files)
        st.download_button(
            "📚 Download Reviewer Package (ZIP)",
            data=reviewer_zip,
            file_name="reviewer_ready_package.zip",
            mime="application/zip",
        )

with main_tabs[0]:
    st.header("Panel Composer (A/B/C/D figure assembly)")
    panel_files = st.file_uploader(
        "Upload processed PNG/JPG panel images", type=["png", "jpg", "jpeg"], accept_multiple_files=True
    )

    if panel_files:
        p1, p2, p3, p4 = st.columns(4)
        with p1:
            columns = st.slider("Columns", 1, 4, 2)
        with p2:
            spacing = st.slider("Spacing", 0, 80, 20)
        with p3:
            bg_color = st.color_picker("Background", "#ffffff")
        with p4:
            label_color = st.color_picker("Label Color", "#000000")

        add_labels = st.checkbox("Add panel labels (A, B, C...)", value=True)
        Image.MAX_IMAGE_PIXELS = None
        images = [Image.open(f).convert("RGB") for f in panel_files]
        composed = compose_panel(
            images=images,
            columns=columns,
            spacing=spacing,
            bg_color=bg_color,
            add_labels=add_labels,
            label_color=label_color,
        )

        st.image(composed, caption="Composed Panel Figure", use_container_width=True)
        st.download_button(
            "⬇️ Download Composed Panel",
            data=image_to_png_bytes(composed),
            file_name="composed_panel.png",
            mime="image/png",
        )

with main_tabs[4]:
    st.header("Project Workspace + Overleaf Export Bundle")

    st.subheader("Save/Load Workspace State")
    workspace_payload = {
        "profile": OUTPUT_PROFILES,
        "timestamp": datetime.now().isoformat(),
        "note": "Bio-TikZ Studio project state",
    }

    st.download_button(
        "💾 Save Workspace (.json)",
        data=build_project_payload(workspace_payload),
        file_name="bio_tikz_workspace.json",
        mime="application/json",
    )

    uploaded_workspace = st.file_uploader("Load Workspace JSON", type=["json"])
    if uploaded_workspace is not None:
        loaded = load_project_payload(uploaded_workspace)
        st.success("Workspace loaded")
        st.json(loaded)

    st.subheader("Overleaf Helper Pack")
    overleaf_preamble = r"""% Add to preamble once
\usepackage{tikz}
\usetikzlibrary{shadows, arrows.meta, positioning, shapes.geometric}
\usepackage[svgnames]{xcolor}
"""

    overleaf_pack = build_zip(
        [
            ("README_Overleaf.md", b"Import snippets from this pack into Overleaf."),
            ("preamble_snippet.tex", overleaf_preamble.encode("utf-8")),
            ("sample_node.tex", generate_tikz_code("Macrophage", "#e74c3c", "circle", "thick", True, "Standard Cell").encode("utf-8")),
            ("sample_legend.tex", generate_legend_tikz([{"label": "Cell", "color": "#e74c3c", "shape": "circle", "style": "solid"}]).encode("utf-8")),
        ]
    )
    st.download_button(
        "📦 Download Overleaf Helper Pack (ZIP)",
        data=overleaf_pack,
        file_name="overleaf_helper_pack.zip",
        mime="application/zip",
    )

    st.subheader("Provenance Ledger + Figure Diff")
    pm_files = [
        ("sample_node.tex", generate_tikz_code("Macrophage", "#e74c3c", "circle", "thick", True, "Standard Cell").encode("utf-8")),
        ("sample_legend.tex", generate_legend_tikz([{"label": "Cell", "color": "#e74c3c", "shape": "circle", "style": "solid"}]).encode("utf-8")),
    ]
    provenance_manifest = build_provenance_manifest(pm_files, {"module": "Project Management", "profile": "Custom"})
    st.code(provenance_manifest, language="json")
    st.download_button("Download provenance_manifest.json", provenance_manifest, "provenance_manifest.json", "application/json")

    prev_json = st.text_area("Previous project JSON", '{"nodes":["A","B"],"edges":1}', key="pm_diff_prev")
    curr_json = st.text_area("Current project JSON", '{"nodes":["A","B","C"],"edges":2}', key="pm_diff_curr")
    st.code(diff_projects(prev_json, curr_json), language="diff")

with main_tabs[1]:
    st.header("Award-Winning Design Strategy Board")
    audience = st.selectbox(
        "Target Context",
        ["Nature/Science-style journal figure", "Conference poster", "Investor or grant presentation"],
    )
    narrative_focus = st.multiselect(
        "Narrative Priorities",
        [
            "Visual hierarchy",
            "Color-blind safe palette",
            "Minimal cognitive load",
            "Strong biological storytelling",
            "Icon consistency",
            "Data-to-annotation balance",
            "Publication typography consistency",
            "One-claim-per-panel clarity",
        ],
        default=["Visual hierarchy", "Strong biological storytelling"],
    )

    st.markdown(
        """
- **Cinematic Layering:** Use foreground/midground/background depth with subtle opacity shifts.
- **Semantic Color Tokens:** Assign one stable color family per entity class.
- **Adaptive Label Density:** Keep concise labels in-figure and move detail to legends.
- **Motion-Ready Composition:** Keep spacing and alignment grid-consistent for talks.
- **Consistency Lock:** Reuse one palette + stroke system across all manuscript figures.
"""
    )

    context_tip = {
        "Nature/Science-style journal figure": "Prioritize grayscale resilience, axis cleanliness, and annotation precision.",
        "Conference poster": "Maximize at-distance readability, larger type, and stronger contrast.",
        "Investor or grant presentation": "Lead with novelty in <5 seconds using a single hero mechanism.",
    }[audience]
    st.success(context_tip)

    design_brief = f"""# Award-Winning Figure Brief
- Target context: {audience}
- Narrative priorities: {', '.join(narrative_focus) if narrative_focus else 'Not selected'}
- Recommended workflow:
  1. Build layout in Panel Composer.
  2. Create consistent symbols in TikZ + Legend Studio.
  3. Validate accessibility and generate reviewer package.
  4. Export helper pack for Overleaf integration.
"""
    st.download_button(
        "📄 Download Design Brief (.md)",
        data=design_brief,
        file_name="award_winning_design_brief.md",
        mime="text/markdown",
    )

with main_tabs[3]:
    st.header("Extraordinary Lab: All 10 Advanced Features")

    st.subheader("1) Mechanistic Connector 2.0")
    n_nodes = st.slider("Number of nodes", 2, 8, 4, key="mech_nodes")
    node_names = [st.text_input(f"Node {i+1}", value=v, key=f"node_{i}") for i, v in enumerate(["Ligand", "Receptor", "MAPK", "Nucleus", "Gene", "Protein", "Cytokine", "Membrane"][:n_nodes])]
    n_edges = st.slider("Number of relations", 1, 12, 3, key="mech_edges")
    edge_rows = []
    for i in range(n_edges):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            src = st.selectbox(f"From {i+1}", node_names, key=f"src_{i}")
        with c2:
            dst = st.selectbox(f"To {i+1}", node_names, index=min(1, len(node_names)-1), key=f"dst_{i}")
        with c3:
            rel = st.selectbox(f"Type {i+1}", list(RELATION_STYLES.keys()), key=f"rel_{i}")
        with c4:
            ev = st.selectbox(f"Evidence {i+1}", ["hypothesis", "literature-supported", "validated"], key=f"ev_{i}")
        edge_rows.append({"source": src, "target": dst, "relation": rel, "evidence": ev})

    mech_tikz = build_mechanistic_tikz(node_names, edge_rows)
    st.code(mech_tikz, language="latex")

    st.subheader("2) Ontology-Aware Auto-Validation")
    issues = ontology_validate_edges(edge_rows)
    if issues:
        for issue in issues:
            st.warning(issue)
    else:
        st.success("No obvious ontology or mechanistic warnings found.")

    st.subheader("3) Figure Quality Auditor (Submission Readiness)")
    qa1, qa2, qa3 = st.columns(3)
    with qa1:
        font_count = st.number_input("Font families used", 1, 10, 2)
    with qa2:
        line_styles_count = st.number_input("Line style count", 1, 10, 3)
    with qa3:
        target_dpi = st.number_input("Target DPI", 72, 1200, 300)
    palette_text = st.text_input("Palette hex list (comma separated)", "#1f77b4,#ff7f0e,#2ca02c")
    palette = [x.strip() for x in palette_text.split(",") if x.strip()]
    readiness, fixes = submission_readiness_score(int(font_count), int(line_styles_count), palette, int(target_dpi))
    st.metric("Submission Readiness", f"{readiness}/100")
    for fix in fixes:
        st.write(f"- {fix}")

    st.subheader("4) AI-to-TikZ Biological Scene Generator")
    ai_prompt = st.text_area("Describe pathway", "Draw TCR signaling with inhibitory PD-1 branch and downstream NFAT blockade.")
    ai_nodes, ai_edges, ai_assumptions = ai_scene_from_prompt(ai_prompt)
    st.json({"nodes": ai_nodes, "edges": ai_edges, "assumptions": ai_assumptions})
    st.code(build_mechanistic_tikz(ai_nodes, ai_edges), language="latex")

    st.subheader("5) Time-Series / State-Transition Diagram Mode")
    states_raw = st.text_input("States (comma separated)", "Baseline,Stimulation,Inhibition,Recovery")
    states = [s.strip() for s in states_raw.split(",") if s.strip()]
    st.code(build_time_series_tikz(states), language="latex")

    st.subheader("6) Reproducible Figure Projects (Versioned)")
    project_state = {
        "timestamp": datetime.now().isoformat(),
        "nodes": node_names,
        "edges": edge_rows,
        "readiness": readiness,
        "fixes": fixes,
    }
    st.download_button("Download versioned project JSON", build_project_payload(project_state), "versioned_figure_project.json", "application/json")

    st.subheader("7) Parametric Bio-Library")
    o1, o2, o3 = st.columns(3)
    with o1:
        organelle = st.selectbox("Organelle", ["Mitochondria", "Golgi", "Lipid Bilayer", "Nucleus"])
    with o2:
        intensity = st.slider("Complexity / density", 10, 100, 50)
    with o3:
        variant = st.text_input("Variant label", "WT")
    st.code(organelle_tikz(organelle, intensity, variant), language="latex")

    st.subheader("8) Experimental Data Overlay")
    overlay_raw = st.text_area("Node,fold_change,p_value (CSV lines)", "Receptor,2.4,0.001\nMAPK,1.6,0.02\nNucleus,0.7,0.18")
    overlay_rows = parse_csv_lines(overlay_raw)
    if overlay_rows:
        st.dataframe([
            {"Node": r[0], "FoldChange": float(r[1]) if len(r) > 1 else 0.0, "p_value": float(r[2]) if len(r) > 2 else 1.0}
            for r in overlay_rows if len(r) >= 3
        ])

    st.subheader("9) Portfolio / Showcase Export Mode")
    portfolio_md = f"""# Bio-TikZ Case Study

- Created: {datetime.now().isoformat()}
- Mechanistic nodes: {len(node_names)}
- Relations: {len(edge_rows)}
- Submission score: {readiness}/100

## Methods
Generated with Bio-TikZ Studio extraordinary workflow with semantic connectors, QA checks, and reproducible config export.
"""
    portfolio_zip = build_zip([
        ("mechanism.tex", mech_tikz.encode("utf-8")),
        ("timeseries.tex", build_time_series_tikz(states).encode("utf-8")),
        ("organelle_template.tex", organelle_tikz(organelle, intensity, variant).encode("utf-8")),
        ("case_study.md", portfolio_md.encode("utf-8")),
        ("project.json", build_project_payload(project_state).encode("utf-8")),
    ])
    st.download_button("Download Portfolio Bundle ZIP", portfolio_zip, "portfolio_bundle.zip", "application/zip")

    st.subheader("10) Collaboration Workflow")
    comment_csv = st.text_area(
        "reviewer,node,status,note (CSV lines)",
        "PI,Receptor,approve,Clear signal start\nReviewer1,MAPK,changes,Need evidence citation\nReviewer2,Nucleus,approve,Looks good",
    )
    comments = parse_csv_lines(comment_csv)
    review_md = collaboration_report(comments)
    st.code(review_md, language="markdown")
    st.download_button("Download collaboration report", review_md, "collaboration_review.md", "text/markdown")


with main_tabs[2]:
    st.header("Publication Panels Toolkit (A/B/C/D)")
    st.caption("Implements requested chemical schemes, significance overlays, flow histogram styling, and auto-layout generator.")

    panel_tabs = st.tabs([
        "Panel A: Chemfig",
        "Panel B&D: Significance Adder",
        "Panel C: Histogram Stylist",
        "Panel Layout Generator",
    ])

    with panel_tabs[0]:
        st.subheader("Chemical Reaction Scheme (Radiochemistry)")
        chemfig_code = st.text_area(
            "Paste chemfig code",
            value="CH_3-CH_2-OH",
            help="Example: *6((-N=-N(-CH_3)-=))",
        )
        chem_caption = st.text_input("Scheme label", "Radiolabeling Step (18F)")
        chem_tex = build_chemfig_document(chemfig_code=chemfig_code, caption=chem_caption)
        st.code(chem_tex, language="latex")
        st.download_button(
            "Download Chemfig .tex",
            chem_tex,
            "panelA_chemfig.tex",
            "text/x-tex",
        )

    with panel_tabs[1]:
        st.subheader("Statistical Bar/Line Plot Significance Adder")
        st.caption("GraphPad/ggplot-style bracket generator + image overlay export for manuscript-ready panel lettering.")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            x1 = st.number_input("Bar/point 1 x", 0.0, 20.0, 1.0)
        with c2:
            x2 = st.number_input("Bar/point 2 x", 0.0, 20.0, 2.0)
        with c3:
            y_sig = st.number_input("Significance y-level", 0.0, 30.0, 5.0)
        with c4:
            stars = st.selectbox("Star annotation", ["*", "**", "***", "****", "ns"], index=2)
        plot_type = st.radio("Plot type", ["bar", "line"], horizontal=True)
        sig_tex = build_significance_tikz(x1=x1, x2=x2, y=y_sig, stars=stars, plot_type=plot_type)
        st.code(sig_tex, language="latex")
        st.download_button("Download Significance .tex", sig_tex, "panelBD_significance.tex", "text/x-tex")

        st.markdown("---")
        st.subheader("Statistical Annotation Overlay (Upload Graph + TikZ Brackets)")
        uploaded_plot = st.file_uploader(
            "Upload graph image (PNG/JPG) for overlay",
            type=["png", "jpg", "jpeg"],
            key="stat_overlay_uploader",
        )

        if uploaded_plot is not None:
            plot_img = Image.open(uploaded_plot).convert("RGB")
            st.image(plot_img, caption="Uploaded graph for overlay", use_container_width=True)

            o1, o2, o3 = st.columns(3)
            with o1:
                panel_label = st.text_input("Panel label", "B")
            with o2:
                image_width_cm = st.number_input("Output width (cm)", 4.0, 30.0, 12.0, step=0.5)
            with o3:
                image_height_cm = st.number_input("Output height (cm)", 3.0, 30.0, 8.0, step=0.5)

            n_brackets = st.slider("Number of significance brackets", 1, 6, 2, key="n_overlay_brackets")
            overlay_brackets = []
            for i in range(n_brackets):
                b1, b2, b3, b4, b5 = st.columns(5)
                with b1:
                    bx1 = st.number_input(f"x1 #{i+1}", 0.0, image_width_cm, 2.0 + i, step=0.1, key=f"ov_x1_{i}")
                with b2:
                    bx2 = st.number_input(f"x2 #{i+1}", 0.0, image_width_cm, 4.0 + i, step=0.1, key=f"ov_x2_{i}")
                with b3:
                    by = st.number_input(f"y #{i+1}", 0.0, image_height_cm, image_height_cm - 1.5 - i * 0.6, step=0.1, key=f"ov_y_{i}")
                with b4:
                    brise = st.number_input(f"rise #{i+1}", 0.1, 2.0, 0.35, step=0.05, key=f"ov_rise_{i}")
                with b5:
                    bstars = st.selectbox(f"stars #{i+1}", ["*", "**", "***", "****", "ns"], index=2, key=f"ov_star_{i}")
                overlay_brackets.append({"x1": bx1, "x2": bx2, "y": by, "rise": brise, "stars": bstars})

            overlay_tex = build_stat_annotation_overlay_tikz(
                image_filename=uploaded_plot.name,
                panel_label=panel_label,
                brackets=overlay_brackets,
                image_width_cm=float(image_width_cm),
                image_height_cm=float(image_height_cm),
            )
            st.code(overlay_tex, language="latex")

            overlay_zip = build_zip([
                (uploaded_plot.name, uploaded_plot.getvalue()),
                ("stat_overlay_panel.tex", overlay_tex.encode("utf-8")),
                ("README_overlay.txt", b"Place image and .tex in same folder, then compile with pdflatex.")
            ])
            st.download_button(
                "Download Overlay Bundle (Image + .tex)",
                overlay_zip,
                "statistical_annotation_overlay_bundle.zip",
                "application/zip",
            )

    with panel_tabs[2]:
        st.subheader("Flow Cytometry / Histogram Stylist")
        h1, h2 = st.columns(2)
        with h1:
            x_steps = st.slider("X grid steps", 4, 15, 8)
        with h2:
            y_steps = st.slider("Y grid steps", 3, 10, 6)
        hist_title = st.text_input("Histogram title", "Flow Overlay (Styled)")
        hist_tex = build_histogram_overlay_tikz(x_steps=x_steps, y_steps=y_steps, title=hist_title)
        st.code(hist_tex, language="latex")
        st.download_button("Download Histogram Overlay .tex", hist_tex, "panelC_histogram_overlay.tex", "text/x-tex")

    with panel_tabs[3]:
        st.subheader("Auto Panel Layout Generator")
        l1, l2, l3 = st.columns(3)
        with l1:
            layout_choice = st.selectbox("Grid", ["2x2", "3x2"], index=0)
        with l2:
            spacing = st.slider("Horizontal spacing", 0.0, 2.5, 0.5, step=0.1)
        with l3:
            show_labels = st.checkbox("Auto labels A, B, C...", value=True)
        layout_tex = build_panel_layout_tikz(layout=layout_choice, spacing=spacing, show_labels=show_labels)
        st.code(layout_tex, language="latex")
        st.download_button("Download Layout .tex", layout_tex, "panel_layout_generator.tex", "text/x-tex")
        
        combined_zip = build_zip([
            ("panelA_chemfig.tex", build_chemfig_document(chemfig_code, chem_caption).encode("utf-8")),
            ("panelBD_significance.tex", sig_tex.encode("utf-8")),
            ("panelC_histogram_overlay.tex", hist_tex.encode("utf-8")),
            ("panel_layout_generator.tex", layout_tex.encode("utf-8")),
        ])
        st.download_button("Download Full Panel Toolkit (ZIP)", combined_zip, "publication_panel_toolkit.zip", "application/zip")


with main_tabs[2]:
    st.header("Scientific Plot Generator")
    st.caption("Grouped bars, dose-response fitting, flow panel formatter, reaction scheme templates, and auto multi-panel builder.")

    sci_tabs = st.tabs([
        "Grouped Bar Plot Builder",
        "Dose-Response Curve Builder",
        "Flow Cytometry Panel Formatter",
        "Reaction Scheme Template Library",
        "Auto Multi-Panel Builder",
    ])

    with sci_tabs[0]:
        st.subheader("Grouped Bar Plot Builder")
        categories_raw = st.text_input("X categories (comma-separated)", "Blood,Heart,Liver")
        groups_raw = st.text_input("Groups (comma-separated)", "10 min,60 min,120 min")
        categories = [x.strip() for x in categories_raw.split(",") if x.strip()]
        groups = [x.strip() for x in groups_raw.split(",") if x.strip()]
        values_raw = st.text_area("Values matrix", "8,11,15\n12,17,20\n15,20,24", height=110)
        errors_raw = st.text_area("Error bars matrix", "0.8,1.2,1.0\n1.1,1.0,1.4\n1.4,1.5,1.6", height=110)
        if categories and groups:
            values = parse_matrix_text(values_raw, rows=len(groups), cols=len(categories), default=0.0)
            errors = parse_matrix_text(errors_raw, rows=len(groups), cols=len(categories), default=0.0)
            gb_img = generate_grouped_bar_plot_image(categories, groups, values, errors)
            gb_pgf = grouped_bar_pgfplots(categories, groups, values, errors)
            st.image(gb_img, caption="Publication-style grouped bar plot", use_container_width=True)
            st.code(gb_pgf, language="latex")
            st.download_button("Download grouped bar PNG", image_to_png_bytes(gb_img), "grouped_bar_plot.png", "image/png")
            st.download_button("Download PGFPlots code", gb_pgf, "grouped_bar_plot.tex", "text/x-tex")

    with sci_tabs[1]:
        st.subheader("Dose-Response Curve Builder (4PL)")
        conc_raw = st.text_input("Concentrations (comma-separated)", "0.01,0.03,0.1,0.3,1,3,10")
        resp_raw = st.text_input("% response (comma-separated)", "95,90,80,65,45,25,10")
        conc = [_safe_float(x, 0.0) for x in conc_raw.split(",") if x.strip()]
        resp = [_safe_float(x, 0.0) for x in resp_raw.split(",") if x.strip()]
        if len(conc) >= 4 and len(conc) == len(resp) and min(conc) > 0:
            fit = fit_4pl_grid(conc, resp)
            dr_img = generate_dose_response_image(conc, resp, fit)
            dr_pgf = dose_response_pgfplots(conc, resp, fit)
            st.metric("Estimated IC50", f"{fit['ec50']:.4g}")
            st.image(dr_img, caption="Dose-response fit", use_container_width=True)
            st.code(dr_pgf, language="latex")
            st.download_button("Download dose-response PNG", image_to_png_bytes(dr_img), "dose_response.png", "image/png")
            st.download_button("Download PGFPlots code", dr_pgf, "dose_response_curve.tex", "text/x-tex")
        else:
            st.info("Provide equal-length concentration/response lists (>=4 points) with positive concentrations.")

    with sci_tabs[2]:
        st.subheader("Flow Cytometry Panel Formatter")
        flow_files = st.file_uploader("Upload histogram PNG/JPG images", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="flow_formatter_uploader")
        cell_line_labels = st.text_input("Cell line labels (comma-separated)", "WT,KO,Rescue")
        quant_raw = st.text_input("Quantification values (comma-separated)", "35,22,48")
        if flow_files:
            imgs = [Image.open(f).convert("RGB") for f in flow_files]
            tw, th = min(im.width for im in imgs), min(im.height for im in imgs)
            normalized = [im.resize((tw, th)) for im in imgs]
            flow_panel = compose_panel(normalized, columns=min(3, len(normalized)), spacing=16, bg_color="#ffffff", add_labels=True, label_color="#000000")
            st.image(flow_panel, caption="Normalized flow panel", use_container_width=True)
            labels = [x.strip() for x in cell_line_labels.split(",") if x.strip()]
            quant = [_safe_float(x, 0.0) for x in quant_raw.split(",") if x.strip()]
            qcats = labels if labels else [f"Group {i+1}" for i in range(len(quant))]
            qvals = [quant[:len(qcats)] if quant else [0.0] * len(qcats)]
            qimg = generate_grouped_bar_plot_image(qcats, ["Quant"], qvals, [[0.0] * len(qcats)], width=1000, height=600)
            st.image(qimg, caption="Auto-generated quantification bar plot", use_container_width=True)
            flow_zip = build_zip([("flow_panel.png", image_to_png_bytes(flow_panel)), ("flow_quantification.png", image_to_png_bytes(qimg))])
            st.download_button("Download flow composite pack (ZIP)", flow_zip, "flow_panel_formatter_pack.zip", "application/zip")

    with sci_tabs[3]:
        st.subheader("Reaction Scheme Template Library")
        template_choice = st.selectbox("Template", ["Radiochemistry", "Peptide Synthesis", "Custom Stepwise"])
        title = st.text_input("Scheme title", template_choice)
        step1 = st.text_input("Left molecule/step", "Precursor")
        step2 = st.text_input("Right molecule/step", "Product")
        cond = st.text_input("Conditions", "18F, 80°C, 20 min")
        rs_tex = reaction_scheme_template(title, step1, step2, cond)
        st.code(rs_tex, language="latex")
        st.download_button("Download reaction scheme .tex", rs_tex, "reaction_scheme_template.tex", "text/x-tex")

    with sci_tabs[4]:
        st.subheader("Auto Multi-Panel Builder (Publication-Ready)")
        multi_files = st.file_uploader("Upload 4-6 PNG/JPG panels", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="multi_panel_uploader")
        m1, m2, m3 = st.columns(3)
        with m1:
            columns_mp = st.selectbox("Columns", [2, 3], index=0)
        with m2:
            spacing_mp = st.slider("Spacing", 8, 60, 20)
        with m3:
            label_color_mp = st.color_picker("Label color", "#000000")
        if multi_files and 4 <= len(multi_files) <= 6:
            mp_imgs = [Image.open(f).convert("RGB") for f in multi_files]
            mw, mh = max(im.width for im in mp_imgs), max(im.height for im in mp_imgs)
            resized = [im.resize((mw, mh)) for im in mp_imgs]
            merged = compose_panel(resized, columns=columns_mp, spacing=spacing_mp, bg_color="#ffffff", add_labels=True, label_color=label_color_mp)
            st.image(merged, caption="Auto-assembled publication panel", use_container_width=True)
            st.download_button("Download multi-panel PNG", image_to_png_bytes(merged), "publication_multi_panel.png", "image/png")
        elif multi_files:
            st.warning("Please upload between 4 and 6 images for this mode.")


st.markdown("---")
st.caption("Developed by Yashwant Nama | PhD Research Portfolio Project")
