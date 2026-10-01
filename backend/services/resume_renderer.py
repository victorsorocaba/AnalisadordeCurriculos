"""Build and compile a fixed LaTeX template from plain-text resume fields."""

import base64
import io
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import pypdfium2 as pdfium

from backend.models.detailed import RenderedResume, ResumeDraft


class RenderError(Exception):
    pass


_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _escape(value: str) -> str:
    return re.sub(r"[\\&%$#_{}~^]", lambda match: _SPECIAL[match.group()], value.strip())


def _experience_lines(content: str) -> list[str]:
    lines = []
    in_list = False
    for raw in content.splitlines():
        item = raw.strip()
        if not item:
            continue
        if "|" in item and len(item) <= 180 and not item.startswith(("-", "•")):
            if in_list:
                lines.append(r"\end{itemize}")
                in_list = False
            lines.append(r"\textbf{" + _escape(item) + r"}\par")
        else:
            if not in_list:
                lines.append(r"\begin{itemize}")
                in_list = True
            lines.append(r"\item " + _escape(item.lstrip("-• ")))
    if in_list:
        lines.append(r"\end{itemize}")
    return lines


def build_latex(draft: ResumeDraft) -> str:
    lines = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[margin=1.8cm]{geometry}",
        r"\usepackage{enumitem}",
        r"\setlist[itemize]{nosep,leftmargin=*}",
        r"\pagestyle{empty}",
        r"\begin{document}",
    ]
    if draft.name.strip():
        lines.append(r"{\LARGE\bfseries " + _escape(draft.name) + r"}\par")
    if draft.headline.strip():
        lines.append(_escape(draft.headline) + r"\par")
    if draft.contact.strip():
        lines.append(_escape(draft.contact) + r"\par")
    lines.append(r"\vspace{0.5em}")
    if draft.summary.strip():
        lines.extend([r"\section*{Resumo Profissional}", _escape(draft.summary) + r"\par"])
    if draft.experience.strip():
        lines.append(r"\section*{Experiência}")
        lines.extend(_experience_lines(draft.experience))
    for title, content in [
        ("Formação", draft.education),
        ("Habilidades", draft.skills),
        ("Projetos", draft.projects),
    ]:
        items = [line.strip().lstrip("-• ") for line in content.splitlines() if line.strip()]
        if items:
            lines.append(r"\section*{" + title + "}")
            lines.append(r"\begin{itemize}")
            lines.extend(r"\item " + _escape(item) for item in items)
            lines.append(r"\end{itemize}")
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def render_resume(draft: ResumeDraft) -> RenderedResume:
    latex = build_latex(draft)
    compiler = shutil.which("xelatex") or shutil.which("pdflatex")
    if not compiler:
        raise RenderError("Nenhum compilador LaTeX foi encontrado. Instale MiKTeX ou TeX Live para gerar o PDF.")
    with tempfile.TemporaryDirectory(prefix="alinha-") as directory:
        source = Path(directory) / "resume.tex"
        source.write_text(latex, encoding="utf-8")
        try:
            completed = subprocess.run(
                [compiler, "-no-shell-escape", "-halt-on-error", "-interaction=nonstopmode", "resume.tex"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError("A compilação do PDF excedeu o tempo permitido.") from exc
        pdf_path = Path(directory) / "resume.pdf"
        if completed.returncode != 0 or not pdf_path.is_file():
            raise RenderError("Não foi possível compilar o PDF. Revise caracteres especiais ou reduza o texto do currículo.")
        pdf = pdf_path.read_bytes()
    preview_pages = []
    document = pdfium.PdfDocument(pdf)
    try:
        for index in range(min(len(document), 4)):
            page = document[index]
            try:
                bitmap = page.render(scale=1.35)
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                preview_pages.append(base64.b64encode(output.getvalue()).decode("ascii"))
            finally:
                page.close()
    finally:
        document.close()
    return RenderedResume(
        latex_code=latex,
        pdf_base64=base64.b64encode(pdf).decode("ascii"),
        preview_pages=preview_pages,
    )
