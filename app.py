import io
import json
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
        color = item["color"].replace("#", "")
        label = item["label"]
        shape = item["shape"]
        style = item.get("style", "solid") # This uses "solid" if "style" is missing
        
        # Draw the shape icon with clean rounded coordinates
        lines.append(
            f"\\node[{shape}, draw, {style}, fill={{[HTML]{{{color}}}!25}}, minimum size=0.45cm] at (0,{round(y, 2)}) {{}};"
        )
        # Draw the text label
        lines.append(f"\\node[anchor=west] at (0.6,{round(y, 2)}) {{{label}}};")
        
        # Decrement y for the next row
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


st.title("🔬 Bio-TikZ Studio | End-to-End Figure Production")
st.caption("Phase 1 + 2 + 3 features: conversion, design, accessibility, composition, packaging, and workflow automation")
st.markdown("---")

main_tabs = st.tabs(
    [
        "🖼️ Converter Lab",
        "🧬 TikZ + Template Studio",
        "🧪 Accessibility + Reviewer Mode",
        "🧩 Panel Composer",
        "📦 Workspace + Export Pack",
        "🏆 Design Strategy",
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
            # Check if a preset exists for this index, otherwise use default
            default_label = st.session_state.get("preset_labels", [f"Entity {j+1}" for j in range(8)])[i]
            label = st.text_input(f"Label {i+1}", default_label, key=f"lab_{i}")
        with l2:
            # Check if a preset color exists, otherwise use default blue
            default_color = st.session_state.get("preset_colors", ["#3498db"] * 8)[i]
            color = st.color_picker(f"Color {i+1}", default_color, key=f"col_{i}")
        with l3:
            shape = st.selectbox(f"Shape {i+1}", ["circle", "rectangle", "ellipse"], key=f"shp_{i}")
        with l4:
            l_style = st.selectbox(f"Style {i+1}", ["solid", "dashed", "dotted", "double"], key=f"sty_{i}")

        legend_items.append({"label": label, "color": color, "shape": shape, "style": l_style})

    legend_code = generate_legend_tikz(legend_items)
    st.code(legend_code, language="latex")
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
        # If the user pasted the whole Overleaf file, we only want the part between \begin{document} and \end{document}
        clean_ai_body = ai_raw_code
        if r"\begin{document}" in ai_raw_code:
            clean_ai_body = ai_raw_code.split(r"\begin{document}")[-1].split(r"\end{document}")[0]
        
        # If they still have \begin{tikzpicture} in there, that's fine, build_full_tikz_document wraps it.
        
        # STEP 2: Wrap in the professional preamble
        ai_final_output = build_full_tikz_document(clean_ai_body)
        
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



with main_tabs[2]:
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

with main_tabs[3]:
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
\usetikzlibrary{shadows,arrows.meta,positioning,shapes.geometric}
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

with main_tabs[5]:
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

st.markdown("---")
st.caption("Developed by Yashwant Nama | PhD Research Portfolio Project")
