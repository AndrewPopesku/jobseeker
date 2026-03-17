import os
import subprocess
import tempfile

from google.adk.tools.tool_context import ToolContext
from google.genai import types


# ---------------------------------------------------------------------------
# LaTeX helpers
# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    """Escape special LaTeX characters in plain text."""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _items(bullets: list[str]) -> str:
    lines = [r"    \begin{itemize}[leftmargin=*, nosep, topsep=2pt]"]
    for b in bullets:
        lines.append(f"        \\item {_escape(b)}")
    lines.append(r"    \end{itemize}")
    return "\n".join(lines)


def _build_latex(user_data: dict) -> str:
    """Render the LaTeX source from user_data dict."""
    name = _escape(user_data.get("name", "Your Name"))
    location = _escape(user_data.get("location", ""))
    phone = _escape(user_data.get("phone", ""))
    email = user_data.get("email", "")
    linkedin = user_data.get("linkedin", "")
    summary = _escape(user_data.get("summary", ""))

    contact_parts = []
    if location:
        contact_parts.append(location)
    if phone:
        contact_parts.append(phone)
    if email:
        contact_parts.append(
            r"\href{mailto:" + email + r"}{\underline{" + _escape(email) + r"}}"
        )
    if linkedin:
        display = linkedin.replace("https://", "").replace("http://", "")
        contact_parts.append(
            r"\href{" + linkedin + r"}{\underline{" + _escape(display) + r"}}"
        )
    contact_line = r" $|$ ".join(contact_parts)

    skills_lines = []
    for category, items in user_data.get("skills", {}).items():
        items_str = _escape(", ".join(items) if isinstance(items, list) else str(items))
        skills_lines.append(
            f"    \\item \\textbf{{{_escape(category)}:}} {items_str}"
        )
    skills_block = "\n".join(skills_lines)

    exp_blocks = []
    for job in user_data.get("experience", []):
        exp_blocks.append(
            f"    \\textbf{{{_escape(job.get('company', ''))}}} \\hfill {_escape(job.get('dates', ''))} \\\\\n"
            f"    \\textit{{{_escape(job.get('title', ''))}}} \\hfill {_escape(job.get('location', ''))}\n"
            + _items(job.get("bullets", []))
            + "\n    \\vspace{6pt}"
        )
    experience_block = "\n\n".join(exp_blocks)

    edu_blocks = []
    for edu in user_data.get("education", []):
        edu_blocks.append(
            f"    \\textbf{{{_escape(edu.get('school', ''))}}} \\hfill {_escape(edu.get('dates', ''))} \\\\\n"
            f"    \\textit{{{_escape(edu.get('degree', ''))}}} \\hfill {_escape(edu.get('location', ''))}"
        )
    education_block = "\n\n".join(edu_blocks)

    cert_section = ""
    if user_data.get("certifications"):
        cert_lines = [f"    \\item {_escape(c)}" for c in user_data["certifications"]]
        cert_section = (
            r"\section*{CERTIFICATIONS}"
            + "\n\\begin{itemize}[leftmargin=*, nosep]\n"
            + "\n".join(cert_lines)
            + "\n\\end{itemize}"
        )

    return rf"""
\documentclass[10pt, letterpaper]{{article}}

\usepackage[top=0.5in, bottom=0.5in, left=0.6in, right=0.6in]{{geometry}}
\usepackage{{enumitem}}
\usepackage{{hyperref}}
\usepackage{{titlesec}}
\usepackage{{parskip}}
\usepackage[T1]{{fontenc}}
\usepackage[utf8]{{inputenc}}

\hypersetup{{colorlinks=true, urlcolor=black, linkcolor=black}}

\titleformat{{\section}}{{\large\bfseries\scshape}}{{}}{{0em}}{{}}[\titlerule]
\titlespacing*{{\section}}{{0pt}}{{6pt}}{{4pt}}

\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0pt}}
\pagestyle{{empty}}

\begin{{document}}

\begin{{center}}
    {{\LARGE \textbf{{{name}}}}} \\[4pt]
    {contact_line}
\end{{center}}

\vspace{{2pt}}

\section*{{SUMMARY}}
{summary}

\section*{{TECHNICAL SKILLS}}
\begin{{itemize}}[leftmargin=*, nosep, topsep=2pt]
{skills_block}
\end{{itemize}}

\section*{{EXPERIENCE}}
{experience_block}

\section*{{EDUCATION}}
{education_block}

{cert_section}

\end{{document}}
""".strip()


# ---------------------------------------------------------------------------
# Tectonic helper
# ---------------------------------------------------------------------------

def _find_tectonic() -> str | None:
    for candidate in ["/opt/homebrew/bin/tectonic", "/usr/local/bin/tectonic", "tectonic"]:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return None


def _compile_tex(tex_path: str) -> dict:
    """Compile a .tex file with tectonic. Returns dict with pdf_path or error."""
    tectonic = _find_tectonic()
    if not tectonic:
        return {"error": "tectonic not found. Install with: brew install tectonic"}

    output_dir = os.path.dirname(tex_path)
    result = subprocess.run(
        [tectonic, "--outdir", output_dir, tex_path],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        return {"error": result.stderr or result.stdout}

    pdf_path = tex_path.replace(".tex", ".pdf")
    if not os.path.isfile(pdf_path):
        return {"error": "PDF not produced after compilation."}

    return {"pdf_path": pdf_path}


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

_CV_ARTIFACT_NAME = "user:cv.pdf"  # user-scoped → persists across sessions


async def generate_and_compile_cv(
    user_data: dict,
    tool_context: ToolContext,
) -> dict:
    """
    Generate a tailored LaTeX CV from structured user data, compile it to PDF
    with Tectonic, and save it as a versioned artifact.

    Args:
        user_data: Dictionary with keys:
            - name (str)
            - location (str)
            - phone (str)
            - email (str)
            - linkedin (str): full URL
            - summary (str): 2-4 sentence professional summary
            - skills (dict): category -> list of skill strings
            - experience (list): [{company, title, dates, location, bullets: [str]}]
            - education (list): [{school, degree, dates, location}]
            - certifications (list, optional)

    Returns:
        Dict with: status, version (int), tex_path, pdf_path, message.
    """
    tmp_dir = tempfile.mkdtemp(prefix="cv_")
    tex_path = os.path.join(tmp_dir, "cv.tex")

    latex_source = _build_latex(user_data)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(latex_source)

    compile_result = _compile_tex(tex_path)
    if "error" in compile_result:
        return {"status": "error", "error": compile_result["error"], "tex_path": tex_path}

    pdf_path = compile_result["pdf_path"]
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    version = await tool_context.save_artifact(
        _CV_ARTIFACT_NAME,
        types.Part(inline_data=types.Blob(mime_type="application/pdf", data=pdf_bytes)),
        custom_metadata={"tex_path": tex_path},
    )

    return {
        "status": "ok",
        "version": version,
        "tex_path": tex_path,
        "pdf_path": pdf_path,
        "message": f"CV compiled and saved as artifact '{_CV_ARTIFACT_NAME}' version {version}.",
    }


async def update_cv_from_latex(
    tex_file_path: str,
    updated_latex_source: str,
    tool_context: ToolContext,
) -> dict:
    """
    Overwrite an existing .tex file with updated LaTeX source, recompile,
    and save a new artifact version.

    Args:
        tex_file_path: Absolute path to the .tex file from a previous generate_and_compile_cv call.
        updated_latex_source: Full updated LaTeX source string.

    Returns:
        Dict with: status, version (int), pdf_path, message.
    """
    with open(tex_file_path, "w", encoding="utf-8") as f:
        f.write(updated_latex_source)

    compile_result = _compile_tex(tex_file_path)
    if "error" in compile_result:
        return {"status": "error", "error": compile_result["error"]}

    pdf_path = compile_result["pdf_path"]
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    version = await tool_context.save_artifact(
        _CV_ARTIFACT_NAME,
        types.Part(inline_data=types.Blob(mime_type="application/pdf", data=pdf_bytes)),
        custom_metadata={"tex_path": tex_file_path},
    )

    return {
        "status": "ok",
        "version": version,
        "pdf_path": pdf_path,
        "message": f"CV updated and saved as artifact '{_CV_ARTIFACT_NAME}' version {version}.",
    }


async def list_cv_versions(tool_context: ToolContext) -> dict:
    """
    List all saved versions of the CV artifact.

    Returns:
        Dict with: versions (list of int), latest (int or None), artifact_name (str).
    """
    svc = tool_context._invocation_context.artifact_service
    if svc is None:
        return {"error": "Artifact service not configured. Run via 'adk web' or with FileArtifactService."}

    inv = tool_context._invocation_context
    versions = await svc.list_versions(
        app_name=inv.app_name,
        user_id=inv.user_id,
        filename=_CV_ARTIFACT_NAME,
        session_id=inv.session.id,
    )

    return {
        "artifact_name": _CV_ARTIFACT_NAME,
        "versions": versions,
        "latest": versions[-1] if versions else None,
    }


async def export_cv_version(version: int, output_path: str, tool_context: ToolContext) -> dict:
    """
    Export a specific version of the CV artifact to a local file.

    Args:
        version: The version number to export (from list_cv_versions).
        output_path: Absolute file path where the PDF should be written (e.g. "/tmp/cv_v2.pdf").

    Returns:
        Dict with: status, output_path, version.
    """
    part = await tool_context.load_artifact(_CV_ARTIFACT_NAME, version=version)
    if part is None:
        return {"status": "error", "error": f"Version {version} of '{_CV_ARTIFACT_NAME}' not found."}

    if not part.inline_data or not part.inline_data.data:
        return {"status": "error", "error": "Artifact has no binary data."}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(part.inline_data.data)

    return {"status": "ok", "output_path": output_path, "version": version}
