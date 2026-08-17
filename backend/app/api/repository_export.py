import logging

from fastapi import APIRouter, HTTPException, Response

from app.export.export_models import PdfExportRequest
from app.export.pdf_renderer import render_markdown_to_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repository/export", tags=["export"])


@router.post("/pdf")
def export_pdf(payload: PdfExportRequest) -> Response:
    """Pure rendering step: takes Markdown the client already assembled from
    data it already fetched, and turns it into a PDF. No repository access,
    no re-running analysis or AI -- this never re-derives anything."""
    try:
        pdf_bytes = render_markdown_to_pdf(payload.title, payload.markdown)
    except Exception as exc:  # noqa: BLE001 - a rendering quirk must never surface a raw traceback to the client
        logger.warning("PDF rendering failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not generate the PDF report. Please try again.") from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="codemap-report.pdf"'},
    )
