#!/usr/bin/env python3
"""
web/admin_routes.py -- Admin endpoints for quality dashboard.

Provides:
- GET /admin/quality -- returns quality_report.json
- GET /admin/quality/html -- returns rendered HTML dashboard
"""

import json
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/quality", summary="Get quality report JSON")
def get_quality_report():
    """Return the quality report as JSON."""
    report_path = Path("context/quality_report.json")
    if not report_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "quality_report.json not found. Run indexing pipeline first."}
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return report
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to read report: {str(e)}"}
        )


@router.get("/quality/html", summary="Render quality dashboard HTML", response_class=HTMLResponse)
def get_quality_dashboard_html():
    """Return rendered HTML dashboard for quality report."""
    report_path = Path("context/quality_report.json")
    if not report_path.exists():
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Quality Dashboard</title><meta charset="utf-8"></head>
        <body>
          <h1>Quality Dashboard</h1>
          <p><strong>Error:</strong> quality_report.json not found. Run indexing pipeline first.</p>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=404)
    
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as e:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Quality Dashboard</title><meta charset="utf-8"></head>
        <body>
          <h1>Quality Dashboard</h1>
          <p><strong>Error:</strong> Failed to read report: {e}</p>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=500)
    
    # Render the HTML template with the report data
    html = _render_quality_html(report)
    return HTMLResponse(content=html)


def _render_quality_html(report: dict) -> str:
    """Render quality report as HTML."""
    
    # Helper to render a table from a list of dicts
    def render_table(items, keys, title="Items"):
        if not items:
            return f"<p>No {title.lower()} to display.</p>"
        
        html = f"<h3>{title}</h3>\n<table border='1' cellpadding='5' style='border-collapse: collapse;'>\n<thead><tr>"
        for k in keys:
            html += f"<th>{k}</th>"
        html += "</tr></thead><tbody>\n"
        
        for item in items:
            html += "<tr>"
            for k in keys:
                val = item.get(k, "")
                if k == "hallucinated_names" and val:
                    val = ", ".join(val[:5]) + ("..." if len(val) > 5 else "")
                html += f"<td>{val}</td>"
            html += "</tr>\n"
        html += "</tbody></table>\n"
        return html
    
    # Build HTML
    html_parts = [
        """<!DOCTYPE html>
        <html lang="en">
        <head>
          <title>Quality Dashboard - Agent Hub</title>
          <meta charset="utf-8">
          <style>
            body { font-family: Arial, sans-serif; margin: 2em; background: #f8f9fa; }
            h1 { color: #333; }
            h2 { color: #444; margin-top: 2em; }
            h3 { color: #555; margin-top: 1.5em; }
            table { background: white; border: 1px solid #ddd; margin-bottom: 1.5em; }
            th, td { padding: 8px 12px; text-align: left; border: 1px solid #ddd; }
            th { background: #f1f1f1; font-weight: bold; }
            .nav { margin-bottom: 2em; padding: 1em; background: white; border-radius: 4px; }
            .error { color: #d32f2f; font-weight: bold; }
            .success { color: #388e3c; font-weight: bold; }
          </style>
        </head>
        <body>
          <h1>⚙️ Quality Dashboard - Agent Hub</h1>
          <div class="nav">
            <a href="/admin">← Back to Admin</a> |
            <a href="/admin/quality">View JSON</a>
          </div>
        """
    ]
    
    # Overall summary
    html_parts.append("<h2>📊 Overall Summary</h2>")
    html_parts.append("<table border='1' cellpadding='5' style='border-collapse: collapse;'>\n<tbody>")
    
    g_version = report.get("g_version", "unknown")
    indexed_at = report.get("indexed_at", "unknown")
    
    html_parts.append(f"<tr><td><strong>Grounding Version</strong></td><td>{g_version}</td></tr>")
    html_parts.append(f"<tr><td><strong>Indexed At</strong></td><td>{indexed_at}</td></tr>")
    
    codex = report.get("codex", {})
    synthesis = report.get("synthesis", {})
    ingest = report.get("ingest", {})
    
    if codex:
        total = codex.get("total_files", 0)
        passed = codex.get("validation_passed", 0)
        abstained = codex.get("abstained", 0)
        failed_then_retried = codex.get("validation_failed_then_retried", 0)
        
        html_parts.append(f"<tr><td><strong>Codex Files</strong></td><td>{total} total</td></tr>")
        html_parts.append(f"<tr><td>✅ Validation Passed</td><td class='success'>{passed}</td></tr>")
        html_parts.append(f"<tr><td>⚠️ Abstained</td><td>{abstained}</td></tr>")
        html_parts.append(f"<tr><td>🔄 Retried & Fixed</td><td>{failed_then_retried}</td></tr>")
        html_parts.append(f"<tr><td>📈 Hallucination Rate</td><td>{((total - passed) / total * 100):.1f}%</td></tr>")
    
    if synthesis:
        total_sections = sum(s.get("sections", 0) for s in synthesis.values())
        total_abstained = sum(s.get("abstained", 0) for s in synthesis.values())
        total_removed = sum(s.get("removed_count", 0) for s in synthesis.values())
        
        html_parts.append(f"<tr><td><strong>Synthesis Sections</strong></td><td>{total_sections} total</td></tr>")
        html_parts.append(f"<tr><td>⚠️ Abstained</td><td>{total_abstained}</td></tr>")
        html_parts.append(f"<tr><td>🗑️ Removed Names</td><td>{total_removed}</td></tr>")
    
    if ingest:
        total_chunks = ingest.get("total_chunks", 0)
        skipped = ingest.get("skipped_incremental", 0)
        added = ingest.get("added", 0)
        
        html_parts.append(f"<tr><td><strong>Ingest Chunks</strong></td><td>{total_chunks} total</td></tr>")
        html_parts.append(f"<tr><td>⏭️ Skipped (unchanged)</td><td>{skipped}</td></tr>")
        html_parts.append(f"<tr><td>➕ Added</td><td>{added}</td></tr>")
    
    html_parts.append("</tbody></table>")
    
    # Codex Section
    if codex and "files" in codex:
        html_parts.append("<h2>📝 Codex - File-by-File Quality</h2>")
        
        failing_files = [f for f in codex.get("files", []) if f.get("abstained") or f.get("hallucinated_names")]
        passing_files = [f for f in codex.get("files", []) if not f.get("abstained") and not f.get("hallucinated_names")]
        
        if failing_files:
            html_parts.append("<h3 class='error'>❌ Failing Files (Abstained or Hallucinated)</h3>")
            html_parts.append(render_table(
                failing_files,
                ["path", "attempts", "abstained", "hallucinated_names"],
                "Failing Files"
            ))
        
        if passing_files:
            html_parts.append("<h3 class='success'>✅ Passing Files</h3>")
            html_parts.append(render_table(
                passing_files[:20],  # Limit to 20 to avoid huge tables
                ["path", "attempts", "abstained", "hallucinated_names"],
                "Passing Files (sample)"
            ))
        
        if not failing_files and not passing_files:
            html_parts.append("<p>No files recorded in quality report.</p>")
    
    # Synthesis Section
    if synthesis:
        html_parts.append("<h2>🏗️ Synthesis - Per-Level Quality</h2>")
        
        levels = []
        for level, data in synthesis.items():
            levels.append({
                "Level": level,
                "Sections": data.get("sections", 0),
                "Abstained": data.get("abstained", 0),
                "Removed Names": data.get("removed_count", 0),
            })
        
        html_parts.append(render_table(levels, ["Level", "Sections", "Abstained", "Removed Names"], "Synthesis Levels"))
    
    # Ingest Section
    if ingest:
        html_parts.append("<h2>📦 Ingest - Chunk Statistics</h2>")
        
        html_parts.append("<table border='1' cellpadding='5' style='border-collapse: collapse;'>\n<tbody>")
        html_parts.append(f"<tr><td><strong>Total Chunks</strong></td><td>{ingest.get('total_chunks', 0)}</td></tr>")
        html_parts.append(f"<tr><td>Skipped (Incremental)</td><td>{ingest.get('skipped_incremental', 0)}</td></tr>")
        html_parts.append(f"<tr><td>Added</td><td>{ingest.get('added', 0)}</td></tr>")
        html_parts.append("</tbody></table>")
    
    html_parts.append("</body></html>")
    return "\n".join(html_parts)
