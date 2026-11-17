"""Playbooks for the web UI, on ``core.playbooks_manager`` (bundled recipes, custom snippets, the PTY runner).

* Values are checked by type with ``check_variable_values`` before anything is rendered: they are pasted into a
  shell script, so free text may only hold characters that can't start a command (a value used only inside single
  quotes may hold anything but a quote or a line break).
* A script that uses sudo needs a choice per run: type the sudo password (answered only to our own random prompt,
  once, and masked in the output; issue #32), or run without one, which turns every ``sudo`` in the script into
  ``sudo -n`` so it fails at once instead of waiting for a password. The password is never stored or logged.
* Destructive recipes need ``confirmed``. One playbook runs at a time; output streams as ``pb.out`` (batched),
  the end as ``pb.done``, and every run is recorded in the history with the last 2,000 characters of its output."""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from typing import Any

from app_web import bus, tasks
from app_web.files import FileError
from app_web.terminals import OutputBuffer
from core.playbooks_manager import (
    PREBUNDLED_RECIPES,
    PlaybookStreamingRunner,
    check_variable_values,
    interpolate_template,
    script_uses_sudo,
)
from core.playbooks_models import PlaybookCategory, PlaybookExecutionRecord, PlaybookRecipe, PlaybookSafetyTier, PlaybookVariable

RUN_KEY = "pb.run"
MAX_SCRIPT = 64 * 1024
NO_PASSWORD_PRELUDE = 'sudo() { command sudo -n "$@"; }\nexport -f sudo\n'
SAFETY_LABELS = {"safe": "Safe", "sudo": "Requires sudo", "destructive": "Destructive"}


class PlaybookError(FileError):
    pass


def recipe_payload(r: PlaybookRecipe) -> dict[str, Any]:
    return {"id": r.id, "title": r.title, "category": str(r.category), "safety": str(r.safety), "safety_label": r.safety_label,
            "description": r.description, "script": r.script_template, "steps": list(r.steps), "custom": not r.is_prebundled,
            "favorite": r.is_favorite, "estimate": r.runtime_estimate, "sudo": script_uses_sudo(r.script_template),
            "variables": [v.to_dict() for v in r.variables]}


class PlaybookService:
    def __init__(self, app_data: Any, session: Any) -> None:
        self.app_data = app_data
        self.session = session
        self._runner: PlaybookStreamingRunner | None = None
        self._out = OutputBuffer(send=lambda _t, p: bus.broadcast("pb.out", {"data": p["data"]}))
        self.running: dict[str, Any] | None = None

    # ---- recipes
    def _custom(self) -> list[PlaybookRecipe]:
        with self.app_data.session_factory() as s:
            return self.app_data.playbooks(s).list_custom_snippets()

    def _find(self, recipe_id: Any) -> PlaybookRecipe:
        found = next((r for r in self._custom() + list(PREBUNDLED_RECIPES) if r.id == recipe_id), None) if isinstance(recipe_id, str) else None
        if found is None:
            raise PlaybookError("That playbook no longer exists.")
        return found

    def list(self) -> dict[str, Any]:
        with self.app_data.session_factory() as s:
            history = self.app_data.playbooks(s).list_history(limit=200)
        last: dict[str, Any] = {}
        for h in history:
            last.setdefault(h.recipe_id, h)
        items = []
        for r in self._custom() + list(PREBUNDLED_RECIPES):
            data = recipe_payload(r)
            h = last.get(r.id)
            data["last"] = {"status": h.status, "at": h.started_at.isoformat(), "ms": h.duration_ms} if h else None
            items.append(data)
        return {"recipes": items, "running": self.running}

    def save(self, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, dict):
            raise PlaybookError("Fill in the snippet.")
        title = spec.get("title") if isinstance(spec.get("title"), str) else ""
        script = spec.get("script") if isinstance(spec.get("script"), str) else ""
        if not title.strip():
            raise PlaybookError("Give the snippet a name.")
        if not script.strip():
            raise PlaybookError("Write the script.")
        if len(script) > MAX_SCRIPT or "\0" in script:
            raise PlaybookError("The script is too large.")
        try:
            category = PlaybookCategory(spec.get("category") or "custom")
            safety = PlaybookSafetyTier(spec.get("safety") or ("sudo" if script_uses_sudo(script) else "safe"))
        except ValueError:
            raise PlaybookError("Choose a category and a safety level.") from None
        existing = None
        if spec.get("id"):
            existing = next((r for r in self._custom() if r.id == spec.get("id")), None)
            if existing is None:
                raise PlaybookError("Bundled playbooks can't be changed. Save a copy as a new snippet.")
        old = {v.key: v for v in (existing.variables if existing else [])}
        keys = list(dict.fromkeys(re.findall(r"\{\{\s*([A-Z][A-Z0-9_]{0,40})\s*\}\}", script)))
        keys += [k for k in re.findall(r"\{\{#if\s+([A-Z][A-Z0-9_]{0,40})\}\}", script) if k not in keys]
        variables = [old.get(k) or PlaybookVariable(key=k, label=k.replace("_", " ").capitalize(), default_value="") for k in keys]
        recipe = PlaybookRecipe(
            id=existing.id if existing else f"custom-{uuid.uuid4().hex[:10]}", title=title.strip()[:120], category=category,
            safety=safety, safety_label=SAFETY_LABELS[safety.value],
            description=(spec.get("description") if isinstance(spec.get("description"), str) else "")[:500],
            script_template=script, variables=variables, steps=[], is_prebundled=False,
            is_favorite=existing.is_favorite if existing else False, runtime_estimate="",
            created_at=existing.created_at if existing else datetime.now())
        with self.app_data.session_factory() as s:
            self.app_data.playbooks(s).add_snippet(recipe)
        return recipe_payload(recipe)

    def delete(self, recipe_id: Any) -> None:
        with self.app_data.session_factory() as s:
            if not isinstance(recipe_id, str) or not self.app_data.playbooks(s).delete_snippet(recipe_id):
                raise PlaybookError("Only your own snippets can be deleted.")

    def favorite(self, recipe_id: Any) -> bool:
        with self.app_data.session_factory() as s:
            if not isinstance(recipe_id, str) or self.app_data.playbooks(s).get_snippet(recipe_id) is None:
                raise PlaybookError("Only your own snippets can be starred.")
            return self.app_data.playbooks(s).toggle_favorite(recipe_id)

    def render(self, recipe_id: Any, values: Any) -> str:
        recipe = self._find(recipe_id)
        try:
            clean = check_variable_values(recipe.variables, values if isinstance(values, dict) else {}, recipe.script_template)
        except ValueError as exc:
            raise PlaybookError(str(exc)) from None
        return interpolate_template(recipe.script_template, clean)

    # ---- run
    def start(self, recipe_id: Any, values: Any, sudo_mode: Any, password: Any, confirmed: Any) -> bool:
        recipe = self._find(recipe_id)
        script = self.render(recipe_id, values)
        connection = self.session.current
        if connection is None or getattr(connection, "raw_connection", None) is None:
            raise PlaybookError("Connect to an SSH server first.")
        if str(recipe.safety) == "destructive" and confirmed is not True:
            raise PlaybookError("This playbook deletes things. Confirm it first.")
        sudo_password = None
        if script_uses_sudo(script):
            if sudo_mode == "password":
                if not isinstance(password, str) or not password:
                    raise PlaybookError("Type the sudo password, or run without one.")
                sudo_password = password
            elif sudo_mode == "none":
                script = NO_PASSWORD_PRELUDE + script
            else:
                raise PlaybookError("This playbook uses sudo. Type the sudo password, or run without one.")
        if tasks.is_running(RUN_KEY):
            raise PlaybookError("A playbook is already running. Wait for it, or stop it.")
        runner = PlaybookStreamingRunner(connection)
        profile_id = getattr(getattr(connection, "profile", None), "id", None)
        started_at, started = datetime.now(), time.monotonic()
        self.running = {"id": recipe.id, "title": recipe.title, "started": started_at.isoformat()}

        async def work() -> None:
            self._runner = runner
            output: list[str] = []

            def on_output(chunk: str) -> None:
                output.append(chunk)
                self._out.push("pb", chunk)

            try:
                result = await runner.run(script, on_output, sudo_password=sudo_password)
            finally:
                self._runner = None
                self.running = None
                self._out.flush()
            data = result.data if isinstance(result.data, dict) else {}
            code = int(data.get("exit_code", 0 if result.ok else 1))
            ms = int(data.get("duration_ms", (time.monotonic() - started) * 1000))
            status = "success" if result.ok else ("cancelled" if code == 130 else "failed")
            text = "".join(output)
            with self.app_data.session_factory() as s:
                self.app_data.playbooks(s).record_execution(PlaybookExecutionRecord(
                    id=str(uuid.uuid4()), recipe_id=recipe.id, recipe_title=recipe.title, profile_id=profile_id,
                    started_at=started_at, duration_ms=ms, exit_code=code, status=status, log_output=text[-2000:]))
            bus.log(f"Playbook {recipe.title}: {result.message}", "ok" if result.ok else "warn", "playbooks")
            bus.broadcast("pb.done", {"id": recipe.id, "ok": result.ok, "status": status, "exit_code": code, "ms": ms,
                                      "message": bus.scrub(result.message)})

        started_ok = tasks.run_task(RUN_KEY, work)
        if not started_ok:
            self.running = None
        else:
            bus.broadcast("pb.started", {"id": recipe.id, "title": recipe.title})
        return started_ok

    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()

    def history(self, recipe_id: Any = None) -> list[dict[str, Any]]:
        titles = {r.id: r.title for r in self._custom() + list(PREBUNDLED_RECIPES)}
        with self.app_data.session_factory() as s:
            rows = self.app_data.playbooks(s).list_history(recipe_id if isinstance(recipe_id, str) else None, limit=50)
        return [{"id": h.id, "recipe_id": h.recipe_id, "title": titles.get(h.recipe_id, h.recipe_id), "at": h.started_at.isoformat(),
                 "ms": h.duration_ms, "exit_code": h.exit_code, "status": h.status, "output": bus.scrub(h.log_output or "")}
                for h in rows]
