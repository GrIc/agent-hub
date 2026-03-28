"""
ProjectAgent -- Base class for project-scoped agents with versioned outputs.
Extends BaseAgent with:
- Project isolation (notes, outputs, reports scoped to a project)
- Versioned document outputs (v1, v2, ...)
- /versions, /rollback, /load commands
"""

import logging
import re
from typing import Optional

from src.agents.base import BaseAgent
from src.projects import Project
from src.rag.ingest import _read_pdf, _read_text

logger = logging.getLogger(__name__)


class ProjectAgent(BaseAgent):
    """
    Base for agents that work within a project scope.
    Subclasses set:
        - doc_type: str (e.g., "requirements", "specifications")
        - output_tag: str (e.g., "requirements_md", "specifications_md")
        - upstream_types: list[str] (doc types to load as context, e.g., ["requirements"])
    """

    doc_type: str = ""
    output_tag: str = ""
    upstream_types: list[str] = []

    def __init__(self, *args, project: Optional[Project] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self._raw_notes: Optional[str] = None
        self._extracted_images: list[dict] = []
        self._image_descriptions: dict[str, str] = {}

    def handle_command(self, cmd: str) -> Optional[str]:
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command == "/load":
            return self._load_project_context()
        if command == "/notes" and self._raw_notes:
            return self._show_notes()
        if command == "/images":
            return self._show_images()
        if command == "/describe" and len(parts) > 1:
            return self._describe_image(parts[1])
        if command == "/draft":
            return self._generate_draft()
        if command == "/finalize":
            return self._finalize()
        if command == "/versions":
            doc = parts[1].strip() if len(parts) > 1 else self.doc_type
            return self._show_versions(doc)
        if command == "/rollback" and len(parts) > 1:
            return self._rollback(parts[1].strip())
        if command == "/status":
            return self._project_status()
        if command == "/alternative":
            return self._generate_alternative()

        return super().handle_command(cmd)

    # -- /load : load notes + upstream outputs ---

    def _load_project_context(self) -> str:
        if not self.project:
            return "No project selected. Use --project <name>."

        lines = []

        # Load notes (for portfolio agent mainly, but available to all)
        notes_dir = self.project.notes_dir
        if notes_dir.exists():
            text_parts = []
            images = []
            files = []
            for ext in ("*.txt", "*.pdf", "*.md"):
                files.extend(sorted(notes_dir.rglob(ext)))

            for f in files:
                rel = f.relative_to(notes_dir)
                if f.suffix.lower() == ".pdf":
                    text, imgs = self._read_pdf_with_images(f)
                    if text.strip():
                        text_parts.append(f"--- [{rel}] ---\n{text}")
                    for img in imgs:
                        img["source_file"] = str(rel)
                    images.extend(imgs)
                else:
                    content = _read_text(f)
                    if content.strip():
                        text_parts.append(f"--- [{rel}] ---\n{content}")

            if text_parts:
                self._raw_notes = "\n\n".join(text_parts)
                lines.append(f"Notes: {len(text_parts)} file(s), {len(self._raw_notes)} chars")
            self._extracted_images = images
            if images:
                lines.append(f"{len(images)} image(s) extracted from PDFs")

        # Load upstream outputs
        for doc_type in self.upstream_types:
            data = self.project.load_latest_output(doc_type)
            if data:
                content, version = data
                lines.append(f"{doc_type}: v{version} loaded ({len(content)} chars)")

        if not lines:
            lines.append("No notes or upstream documents found.")
            lines.append(f"   Put notes in projects/{self.project.name}/notes/")

        return "\n".join(lines)

    def _show_notes(self) -> str:
        if not self._raw_notes:
            return "No notes loaded. Use /load first."
        count = self._raw_notes.count("--- [")
        preview = self._raw_notes[:500] + ("\n[...]" if len(self._raw_notes) > 500 else "")
        return f"Notes: {count} source(s), {len(self._raw_notes)} chars\n\nPreview:\n{preview}"

    # -- Images (from PDFs) ---

    def _read_pdf_with_images(self, path):
        """Extract text + images from PDF."""
        from pathlib import Path as P
        OUTPUT_IMAGES = P("output/images")
        text_parts, images_info = [], []
        try:
            import fitz
            doc = fitz.open(str(path))
            OUTPUT_IMAGES.mkdir(parents=True, exist_ok=True)
            pdf_stem = path.stem
            for page_num, page in enumerate(doc, 1):
                text = page.get_text()
                if text.strip():
                    text_parts.append(f"[Page {page_num}]\n{text}")
                for img_idx, img_info in enumerate(page.get_images(full=True)):
                    try:
                        base = doc.extract_image(img_info[0])
                        if not base or base.get("width", 0) < 50 or base.get("height", 0) < 50:
                            continue
                        fname = f"{pdf_stem}_p{page_num}_img{img_idx+1}.{base.get('ext','png')}"
                        (OUTPUT_IMAGES / fname).write_bytes(base["image"])
                        images_info.append({"page": page_num, "index": img_idx+1, "path": str(OUTPUT_IMAGES/fname),
                                            "filename": fname, "width": base["width"], "height": base["height"],
                                            "size_kb": len(base["image"])//1024})
                    except Exception:
                        pass
            doc.close()
        except Exception as e:
            logger.warning(f"Cannot parse PDF {path}: {e}")
        return "\n\n".join(text_parts), images_info

    def _show_images(self) -> str:
        if not self._extracted_images:
            return "No images extracted. Use /load on a project with PDFs."
        lines = [f"{len(self._extracted_images)} extracted image(s):", ""]
        for i, img in enumerate(self._extracted_images, 1):
            desc = self._image_descriptions.get(img["filename"])
            status = f"Described: {desc[:80]}..." if desc else "Not described"
            lines.append(f"  [{i}] {img['filename']} -- {img['width']}x{img['height']}px -- {status}")
        return "\n".join(lines)

    def _describe_image(self, args: str) -> str:
        if not self._extracted_images:
            return "No extracted images."
        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /describe <number> <description>"
        try:
            idx = int(parts[0]) - 1
        except ValueError:
            return f"'{parts[0]}' is not a number."
        if idx < 0 or idx >= len(self._extracted_images):
            return f"Invalid number. Available: 1 to {len(self._extracted_images)}"
        img = self._extracted_images[idx]
        self._image_descriptions[img["filename"]] = parts[1].strip()
        if self._raw_notes:
            self._raw_notes += f"\n--- [Image: {img['filename']}] ---\nUser description: {parts[1].strip()}\n"
        return f"Image [{idx+1}] described: {img['filename']}"

    # -- Context injection ---

    def build_messages(self, user_message: str) -> list[dict]:
        context = self.retrieve_context(user_message)
        peer_context = self.get_peer_reports()

        system = self.get_system_prompt()

        if peer_context:
            system += f"\n\n{peer_context}"

        # Inject project context: upstream outputs
        if self.project:
            for doc_type in self.upstream_types:
                data = self.project.load_latest_output(doc_type)
                if data:
                    content, version = data
                    if len(content) > 4000:
                        content = content[:4000] + "\n[... truncated]"
                    system += f"\n\n## Project document: {doc_type} (v{version})\n{content}"

        # Inject raw notes if loaded
        if self._raw_notes:
            excerpt = self._raw_notes[:6000]
            if len(self._raw_notes) > 6000:
                excerpt += "\n[... truncated]"
            system += f"\n\n## Raw notes\n{excerpt}"

        # RAG context
        if context:
            system += f"\n\n## Retrieved context (codebase)\n{context}"

        messages = [{"role": "system", "content": system}]
        messages.extend(self.history[-20:])
        messages.append({"role": "user", "content": user_message})
        return messages

    # -- Draft / Finalize / Alternative ---

    def _generate_draft(self) -> str:
        if not self.project:
            return "No project selected."
        prompt = (
            f"Generate a DRAFT {self.doc_type} document based on everything you know "
            f"(notes, upstream documents, our conversation). "
            f"Mark incomplete areas with [TO BE CLARIFIED]. "
            f"Use the {self.output_tag} format."
        )
        return self.chat(prompt)

    def _finalize(self) -> str:
        if not self.project:
            return "No project selected."
        prompt = (
            f"Generate the FINAL {self.doc_type} document. "
            f"Everything marked [TO BE CLARIFIED] must be resolved or listed in Assumptions. "
            f"Use the {self.output_tag} format."
        )
        return self.chat(prompt)

    def _generate_alternative(self) -> str:
        prompt = (
            f"Propose a RADICALLY DIFFERENT approach from what was discussed so far. "
            f"Different trade-offs, different architecture, different priorities. "
            f"Use the {self.output_tag} format."
        )
        return self.chat(prompt)

    # -- Versioning commands ---

    def _show_versions(self, doc_type: str) -> str:
        if not self.project:
            return "No project selected."
        versions = self.project.list_versions(doc_type)
        if not versions:
            return f"No versions found for '{doc_type}'."
        lines = [f"Versions of '{doc_type}':", ""]
        for v in versions:
            lines.append(f"  v{v['version']} -- {v['modified']} ({v['size']} bytes)")
        return "\n".join(lines)

    def _rollback(self, args: str) -> str:
        if not self.project:
            return "No project selected."
        parts = args.split()
        doc_type = parts[0] if len(parts) > 1 else self.doc_type
        try:
            version = int(parts[-1])
        except ValueError:
            return "Usage: /rollback [doc_type] <version_number>"
        if self.project.rollback_output(doc_type, version):
            return f"Rolled back '{doc_type}' to v{version}. Later versions deleted."
        return f"Nothing to rollback for '{doc_type}' to v{version}."

    def _project_status(self) -> str:
        if not self.project:
            return "No project selected."
        lines = [f"Project: {self.project.name}", ""]

        notes = list(self.project.notes_dir.rglob("*")) if self.project.notes_dir.exists() else []
        notes = [f for f in notes if f.is_file()]
        lines.append(f"  Notes: {len(notes)} file(s)")

        outputs = self.project.get_all_latest_outputs()
        if outputs:
            lines.append(f"  Outputs:")
            for doc_type, (content, version) in sorted(outputs.items()):
                lines.append(f"    {doc_type}: v{version} ({len(content)} chars)")
        else:
            lines.append(f"  Outputs: none yet")

        reports = list(self.project.reports_dir.glob("*.md")) if self.project.reports_dir.exists() else []
        lines.append(f"  Reports: {len(reports)} file(s)")

        return "\n".join(lines)

    # -- Post-process: save versioned output ---

    def post_process(self, response: str) -> str:
        if not self.project or not self.output_tag:
            return response

        match = re.search(rf"```{self.output_tag}\s*(.*?)\s*```", response, re.DOTALL)
        if not match:
            return response

        try:
            content = match.group(1).strip()
            filepath, version = self.project.save_output(self.doc_type, content)
            self.log_action(f"{self.doc_type} v{version} saved")
            self.log_file(filepath)
            return (
                f"{response}\n\n"
                f"{self.doc_type} v{version} saved: {filepath}\n"
                f"   /versions {self.doc_type} -- to see all versions\n"
                f"   /rollback {self.doc_type} {version-1} -- to go back"
            )
        except Exception as e:
            logger.error(f"Save failed: {e}")
            return f"{response}\n\nSave error: {e}"

    # -- Help ---

    def _help_text(self) -> str:
        return (
            super()._help_text()
            + f"\nProject commands:\n"
            f"  /load                     -- Load project notes and upstream documents\n"
            f"  /status                   -- Project overview (notes, outputs, reports)\n"
            f"  /draft                    -- Generate a draft {self.doc_type}\n"
            f"  /finalize                 -- Generate final {self.doc_type}\n"
            f"  /alternative              -- Propose a radically different approach\n"
            f"  /versions [{self.doc_type}]  -- List all versions\n"
            f"  /rollback [{self.doc_type}] N -- Rollback to version N\n"
            f"  /notes                    -- Show loaded notes\n"
            f"  /images                   -- List extracted images\n"
            f"  /describe N desc          -- Describe an image\n"
        )
