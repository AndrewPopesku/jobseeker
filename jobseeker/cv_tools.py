import os

import requests
from google.adk.tools.tool_context import ToolContext
from google.genai import types

import google.auth.transport.requests
import google.oauth2.id_token


_COMPILER_URL = os.environ.get("COMPILER_SERVICE_URL", "http://localhost:8081")


def _auth_headers() -> dict:
    """Return auth headers for Cloud Run service-to-service calls."""
    if _COMPILER_URL.startswith("http://"):
        return {}  # local dev, no auth needed
    token = google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), _COMPILER_URL
    )
    return {"Authorization": f"Bearer {token}"}


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


def _resume_item(text: str) -> str:
    return f"    \\resumeItem{{{_escape(text)}}}"


def _subheading(col1: str, col2: str, col3: str, col4: str) -> str:
    return (
        "    \\resumeSubheading\n"
        f"      {{{_escape(col1)}}}{{{_escape(col2)}}}\n"
        f"      {{{_escape(col3)}}}{{{_escape(col4)}}}"
    )


def _build_latex(user_data: dict) -> str:
    """Render the LaTeX source from user_data dict."""
    name = _escape(user_data.get("name", "Your Name"))
    location = _escape(user_data.get("location", ""))
    phone = user_data.get("phone", "")
    email = user_data.get("email", "")
    linkedin = user_data.get("linkedin", "")
    summary = _escape(user_data.get("summary", ""))

    contact_line = (
        f"    \\small {_escape(location)}"
        + (f" $|$ \\faPhone\\ {_escape(phone)}" if phone else "")
        + (f" $|$ \\faEnvelope\\ \\href{{mailto:{email}}}{{\\underline{{{_escape(email)}}}}}" if email else "")
        + (f" $|$ \\faLinkedin\\ \\href{{{linkedin}}}{{\\underline{{{_escape(linkedin.replace('https://', '').replace('http://', ''))}}}}}" if linkedin else "")
    )

    skills_lines = []
    for category, items in user_data.get("skills", {}).items():
        items_str = _escape(", ".join(items) if isinstance(items, list) else str(items))
        skills_lines.append(f"     \\textbf{{{_escape(category)}}}{{: {items_str}}} \\\\")
    skills_block = "\n".join(skills_lines)

    exp_blocks = []
    for job in user_data.get("experience", []):
        bullets = "\n".join(_resume_item(b) for b in job.get("bullets", []))
        exp_blocks.append(
            _subheading(job.get("company", ""), job.get("location", ""), job.get("title", ""), job.get("dates", ""))
            + "\n      \\resumeItemListStart\n"
            + bullets
            + "\n      \\resumeItemListEnd"
        )
    experience_block = "\n\n".join(exp_blocks)

    edu_blocks = []
    for edu in user_data.get("education", []):
        edu_blocks.append(
            _subheading(edu.get("school", ""), edu.get("location", ""), edu.get("degree", ""), edu.get("dates", ""))
        )
    education_block = "\n\n".join(edu_blocks)

    hackathon_block = ""
    if user_data.get("hackathons"):
        items = []
        for h in user_data["hackathons"]:
            bullets = "\n".join(_resume_item(b) for b in h.get("bullets", []))
            items.append(
                _subheading(h.get("title", ""), h.get("location", ""), h.get("role", ""), h.get("dates", ""))
                + "\n      \\resumeItemListStart\n"
                + bullets
                + "\n      \\resumeItemListEnd"
            )
        hackathon_block = (
            "\\section{Hackathon}\n  \\resumeSubHeadingListStart\n"
            + "\n\n".join(items)
            + "\n  \\resumeSubHeadingListEnd\n"
        )

    cert_section = ""
    if user_data.get("certifications"):
        cert_lines = "\n".join(f"    \\resumeItem{{{_escape(c)}}}" for c in user_data["certifications"])
        cert_section = (
            "\\section{Certifications}\n  \\resumeSubHeadingListStart\n"
            "  \\resumeItemListStart\n"
            + cert_lines
            + "\n  \\resumeItemListEnd\n  \\resumeSubHeadingListEnd"
        )

    preamble = r"""
\documentclass[letterpaper,11pt]{article}

\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\usepackage{fontawesome5}

\ifdefined\pdfgentounicode
  \input{glyphtounicode}
  \pdfgentounicode=1
\fi

\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}

\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

\titleformat{\section}{\vspace{-4pt}\scshape\raggedright\large\bfseries}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]

\newcommand{\resumeItem}[1]{\item\small{{#1 \vspace{-2pt}}}}
\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
"""

    body = f"""
\\begin{{document}}

\\begin{{center}}
    \\textbf{{\\Huge \\scshape {name}}} \\\\ \\vspace{{3pt}}
{contact_line}
\\end{{center}}

\\section{{Summary}}
\\small{{{summary}}}

\\section{{Technical Skills}}
 \\begin{{itemize}}[leftmargin=0.15in, label={{}}]
    \\small{{\\item{{
{skills_block}
    }}}}
 \\end{{itemize}}

{hackathon_block}

\\section{{Experience}}
  \\resumeSubHeadingListStart
{experience_block}
  \\resumeSubHeadingListEnd

\\section{{Education}}
  \\resumeSubHeadingListStart
{education_block}
  \\resumeSubHeadingListEnd

{cert_section}

\\end{{document}}
"""

    return (preamble + body).strip()


# ---------------------------------------------------------------------------
# Compiler service client
# ---------------------------------------------------------------------------

def _compile_remote(latex_source: str) -> bytes:
    """Send LaTeX source to the compiler service, return PDF bytes."""
    resp = requests.post(
        f"{_COMPILER_URL}/compile",
        json={"latex_source": latex_source},
        headers=_auth_headers(),
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Compiler service error ({resp.status_code}): {resp.text}")
    return resp.content


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
    via the compiler service, and save it as a versioned artifact.

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
        Dict with: status, version (int), latex_source, message.
    """
    latex_source = _build_latex(user_data)
    pdf_bytes = _compile_remote(latex_source)

    version = await tool_context.save_artifact(
        _CV_ARTIFACT_NAME,
        types.Part(inline_data=types.Blob(mime_type="application/pdf", data=pdf_bytes)),
        custom_metadata={"latex_source": latex_source},
    )

    return {
        "status": "ok",
        "version": version,
        "latex_source": latex_source,
        "message": f"CV compiled and saved as artifact '{_CV_ARTIFACT_NAME}' version {version}.",
    }


async def update_cv_from_latex(
    updated_latex_source: str,
    tool_context: ToolContext,
) -> dict:
    """
    Compile updated LaTeX source to PDF via the compiler service
    and save a new artifact version.

    Args:
        updated_latex_source: Full updated LaTeX source string.

    Returns:
        Dict with: status, version (int), message.
    """
    pdf_bytes = _compile_remote(updated_latex_source)

    version = await tool_context.save_artifact(
        _CV_ARTIFACT_NAME,
        types.Part(inline_data=types.Blob(mime_type="application/pdf", data=pdf_bytes)),
        custom_metadata={"latex_source": updated_latex_source},
    )

    return {
        "status": "ok",
        "version": version,
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
        raise RuntimeError("Artifact service not configured. Run via 'adk web' or with FileArtifactService.")

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
        raise ValueError(f"Version {version} of '{_CV_ARTIFACT_NAME}' not found.")

    if not part.inline_data or not part.inline_data.data:
        raise ValueError("Artifact has no binary data.")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(part.inline_data.data)

    return {"status": "ok", "output_path": output_path, "version": version}
