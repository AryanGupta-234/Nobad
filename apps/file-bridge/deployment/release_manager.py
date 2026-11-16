from __future__ import annotations

import posixpath
from dataclasses import dataclass

from core.connections.ssh_async import sh_quote
from core.result import OperationResult
from file_ops.safety import normalize_remote_path

from deployment.deployment_job import DeploymentJob


@dataclass(slots=True)
class AtomicReleaseContext:
    target_path: str
    releases_root: str
    staging_path: str
    release_path: str
    previous_release_path: str | None = None
    adopted_release_path: str | None = None
    target_was_missing: bool = False
    switched: bool = False


class ReleaseManager:
    def releases_root(self, job: DeploymentJob) -> str:
        target = normalize_remote_path(job.remote_target_folder)
        parent = posixpath.dirname(target.rstrip("/")) or "/"
        return posixpath.join(parent, ".rfm-releases", job.id)

    async def prepare(self, connection, job: DeploymentJob, run_id: str) -> OperationResult:  # type: ignore[no-untyped-def]
        target = normalize_remote_path(job.remote_target_folder)
        root = self.releases_root(job)
        release_path = posixpath.join(root, run_id)
        staging_path = release_path + ".staging"
        inspection = await self.inspect_target(connection, job)
        if not inspection.ok:
            return inspection
        target_info = inspection.data
        kind = target_info["kind"]
        current = target_info.get("resolved")
        adopted: str | None = None
        target_was_missing = kind == "missing"

        if kind == "other":
            return OperationResult.failure("Atomic deployment target exists but is not a directory or symlink.")
        if kind == "external_symlink":
            return OperationResult.failure(
                "Atomic deployment target points outside this job's release directory.",
                suggested_fix="Use in-place deployment or manually prepare a compatible release symlink.",
            )

        setup = await self._run_checked(
            connection,
            f"mkdir -p {sh_quote(root)} && rm -rf -- {sh_quote(staging_path)} {sh_quote(release_path)}",
            "Could not prepare the atomic release directory.",
        )
        if not setup.ok:
            return setup
        if kind == "directory":
            adopted = posixpath.join(root, f"adopted-{run_id}")
            adoption = await self._run_checked(
                connection,
                f"mv -- {sh_quote(target)} {sh_quote(adopted)} && "
                f"ln -s {sh_quote(adopted)} {sh_quote(target)}",
                "Could not adopt the existing target as an atomic release.",
            )
            if not adoption.ok:
                await connection.run_command(
                    f"if test -d {sh_quote(adopted)} && ! test -e {sh_quote(target)}; "
                    f"then mv -- {sh_quote(adopted)} {sh_quote(target)}; fi"
                )
                return adoption
            current = adopted
        commands: list[str] = []
        if current:
            commands.extend(
                [
                    f"mkdir -p {sh_quote(staging_path)}",
                    f"cp -a {sh_quote(current + '/.')} {sh_quote(staging_path + '/')}",
                ]
            )
        else:
            commands.append(f"mkdir -p {sh_quote(staging_path)}")

        result = await self._run_checked(
            connection,
            " && ".join(commands),
            "Could not prepare the atomic release staging directory.",
        )
        if not result.ok:
            if adopted:
                await connection.run_command(
                    f"rm -f -- {sh_quote(target)} && "
                    f"mv -- {sh_quote(adopted)} {sh_quote(target)} && "
                    f"rm -rf -- {sh_quote(staging_path)} {sh_quote(release_path)}"
                )
            return result
        context = AtomicReleaseContext(
            target_path=target,
            releases_root=root,
            staging_path=staging_path,
            release_path=release_path,
            previous_release_path=current,
            adopted_release_path=adopted,
            target_was_missing=target_was_missing,
        )
        return OperationResult.success("Atomic release staging prepared.", data=context)

    async def inspect_target(self, connection, job: DeploymentJob) -> OperationResult:  # type: ignore[no-untyped-def]
        target = normalize_remote_path(job.remote_target_folder)
        root = self.releases_root(job)
        command = (
            f"if test -L {sh_quote(target)}; then printf 'symlink\\n'; readlink -f {sh_quote(target)}; "
            f"elif test -d {sh_quote(target)}; then printf 'directory\\n'; "
            f"elif test -e {sh_quote(target)}; then printf 'other\\n'; "
            "else printf 'missing\\n'; fi"
        )
        result = await connection.run_command(command)
        data = result.data if isinstance(result.data, dict) else {}
        if not result.ok or int(data.get("exit_status", 1)) != 0:
            return OperationResult.failure(
                "Could not inspect the atomic deployment target.",
                technical_details=str(data.get("stderr") or result.technical_details or "") or None,
            )
        lines = str(data.get("stdout") or "").splitlines()
        kind = lines[0].strip() if lines else "other"
        resolved = lines[1].strip() if len(lines) > 1 else None
        if kind == "symlink":
            normalized_root = root.rstrip("/") + "/"
            if not resolved or not resolved.startswith(normalized_root):
                kind = "external_symlink"
        return OperationResult.success(
            "Atomic target inspected.",
            data={"kind": kind, "resolved": resolved, "releases_root": root},
        )

    async def switch(self, connection, context: AtomicReleaseContext) -> OperationResult:  # type: ignore[no-untyped-def]
        temporary_link = context.target_path + f".rfm-next-{posixpath.basename(context.release_path)}"
        command = (
            f"rm -f -- {sh_quote(temporary_link)} && "
            f"mv -- {sh_quote(context.staging_path)} {sh_quote(context.release_path)} && "
            f"ln -s {sh_quote(context.release_path)} {sh_quote(temporary_link)} && "
            f"mv -Tf -- {sh_quote(temporary_link)} {sh_quote(context.target_path)}"
        )
        result = await self._run_checked(connection, command, "Could not switch the atomic release.")
        if result.ok:
            context.switched = True
        return result

    async def rollback(self, connection, context: AtomicReleaseContext) -> OperationResult:  # type: ignore[no-untyped-def]
        if context.switched:
            if context.previous_release_path:
                return await self.switch_to(connection, context.target_path, context.previous_release_path)
            return await self._run_checked(
                connection,
                f"rm -f -- {sh_quote(context.target_path)}",
                "Could not remove the failed first release symlink.",
            )
        if context.adopted_release_path:
            command = (
                f"rm -f -- {sh_quote(context.target_path)} && "
                f"mv -- {sh_quote(context.adopted_release_path)} {sh_quote(context.target_path)} && "
                f"rm -rf -- {sh_quote(context.staging_path)} {sh_quote(context.release_path)}"
            )
            return await self._run_checked(connection, command, "Could not undo atomic target adoption.")
        return await self._run_checked(
            connection,
            f"rm -rf -- {sh_quote(context.staging_path)} {sh_quote(context.release_path)}",
            "Could not clean the failed release staging directory.",
        )

    async def switch_to(self, connection, target_path: str, release_path: str) -> OperationResult:  # type: ignore[no-untyped-def]
        temporary_link = target_path + ".rfm-rollback-next"
        command = (
            f"rm -f -- {sh_quote(temporary_link)} && "
            f"ln -s {sh_quote(release_path)} {sh_quote(temporary_link)} && "
            f"mv -Tf -- {sh_quote(temporary_link)} {sh_quote(target_path)}"
        )
        return await self._run_checked(connection, command, "Could not switch to the selected release.")

    async def list_releases(self, connection, job: DeploymentJob) -> OperationResult:  # type: ignore[no-untyped-def]
        root = self.releases_root(job)
        command = (
            f"if test -d {sh_quote(root)}; then "
            f"find {sh_quote(root)} -mindepth 1 -maxdepth 1 -type d "
            "! -name '*.staging' -printf '%T@|%p\\n' | sort -nr; fi"
        )
        result = await connection.run_command(command)
        data = result.data if isinstance(result.data, dict) else {}
        if not result.ok or int(data.get("exit_status", 1)) != 0:
            return OperationResult.failure(
                "Could not list atomic releases.",
                technical_details=str(data.get("stderr") or result.technical_details or "") or None,
            )
        releases = []
        for line in str(data.get("stdout") or "").splitlines():
            _timestamp, separator, path = line.partition("|")
            if separator and path:
                releases.append(path)
        return OperationResult.success("Atomic releases listed.", data=releases)

    async def prune(
        self,
        connection,
        job: DeploymentJob,
        *,
        active_path: str | None,
        previous_path: str | None,
    ) -> OperationResult:
        listed = await self.list_releases(connection, job)
        if not listed.ok:
            return listed
        protected = {path for path in [active_path, previous_path] if path}
        removable = [path for path in listed.data if path not in protected]
        keep_extra = max(0, int(job.release_retention) - len(protected))
        for path in removable[keep_extra:]:
            result = await self._run_checked(
                connection,
                f"rm -rf -- {sh_quote(path)}",
                "Could not prune an old atomic release.",
            )
            if not result.ok:
                return result
        return OperationResult.success("Old atomic releases pruned.")

    async def _run_checked(self, connection, command: str, message: str) -> OperationResult:  # type: ignore[no-untyped-def]
        result = await connection.run_command(command)
        data = result.data if isinstance(result.data, dict) else {}
        if result.ok and int(data.get("exit_status", 1)) == 0:
            return OperationResult.success(message.replace("Could not ", "").rstrip(".") + ".")
        return OperationResult.failure(
            message,
            technical_details=str(data.get("stderr") or result.technical_details or "") or None,
        )
