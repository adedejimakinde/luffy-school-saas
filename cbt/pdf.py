"""Exam slips as a PDF: the same path as the result checker's slips (`results.pdf`).

Rendered **in the request that mints the PINs**, by WeasyPrint from a Django template,
and handed back as the response. Nothing is written to disk, to storage or to a cache:
the raw PINs exist only in that response, and a file kept for later would be the PINs
at rest.
"""

from django.template.loader import render_to_string


def slips_html(slips, sit_address: str) -> str:
    """The slips' HTML before WeasyPrint sees it, so a test can read it as text."""
    return render_to_string(
        "cbt/exam_slips.html",
        {
            "school_name": slips.school_name,
            "class_group_name": slips.class_group_name,
            "term_label": slips.term_label,
            "session": slips.session,
            "slips": slips.slips,
            "without_a_number": slips.without_a_number,
            "sit_address": sit_address,
        },
    )


def render_slips(slips, sit_address: str) -> bytes:
    """One press's exam slips as PDF bytes."""
    from weasyprint import HTML

    return HTML(string=slips_html(slips, sit_address)).write_pdf()


__all__ = ["render_slips", "slips_html"]
