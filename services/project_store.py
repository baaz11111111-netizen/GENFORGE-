"""Atomic JSON persistence for project history and render versions."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .project_model import ProjectState


class ProjectStore:
    def __init__(self, root: str | Path = "projects") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, project_id: str) -> Path:
        if not project_id or not project_id.strip() or Path(project_id).name != project_id or project_id in {".", ".."}:
            raise ValueError("Invalid project id")
        return self.root / project_id / "project.json"

    def save(self, project: ProjectState) -> Path:
        destination = self.path_for(project.project_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, destination)
        return destination

    def load(self, project_id: str) -> ProjectState:
        source = self.path_for(project_id)
        if not source.is_file():
            raise FileNotFoundError(f"Project not found: {project_id}")
        try:
            return ProjectState.model_validate(json.loads(source.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"Could not load project: {project_id}") from exc

    def list_projects(self) -> list[ProjectState]:
        """Load valid saved projects, newest-first by updated_at, without exposing bad entries."""
        projects: list[ProjectState] = []
        for entry in self.root.iterdir():
            if not entry.is_dir():
                continue
            try:
                projects.append(self.load(entry.name))
            except (FileNotFoundError, OSError, RuntimeError, ValueError):
                continue
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)

    def delete(self, project_id: str, output_root: str | Path = "outputs") -> None:
        """Delete one project directory and its project-scoped output directory."""
        project_file = self.path_for(project_id)
        project_dir = project_file.parent
        if project_dir.parent != self.root:
            raise ValueError("Invalid project directory")
        if project_dir.exists():
            shutil.rmtree(project_dir)

        output_base = Path(output_root).resolve()
        output_dir = (output_base / project_id).resolve()
        if output_dir.parent != output_base:
            raise ValueError("Invalid project output directory")
        if output_dir.exists():
            shutil.rmtree(output_dir)

    def delete_all(self, output_root: str | Path = "outputs") -> int:
        """Delete every saved project and return the count of removed projects.

        Only project directories confirmed by list_projects() are removed.
        Unrelated files and directories inside self.root are left untouched.
        Application configuration, code, and non-project output dirs are
        protected by the same path-validation logic used by delete().
        """
        projects = self.list_projects()
        for project in projects:
            self.delete(project.project_id, output_root=output_root)
        return len(projects)
