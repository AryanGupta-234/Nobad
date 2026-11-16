from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DeploymentTemplate:
    name: str
    build_command: str = ""
    build_folder: str = ""
    post_deploy_command: str = ""
    restart_command: str = ""
    ignore_patterns: list[str] = field(default_factory=list)


DEPLOYMENT_TEMPLATES = [
    DeploymentTemplate(
        name="Generic Folder",
        ignore_patterns=[".git", ".DS_Store", "__pycache__"],
    ),
    DeploymentTemplate(
        name="Static / React / Vite",
        build_command="npm run build",
        build_folder="dist",
        ignore_patterns=["node_modules", ".git", ".env", ".DS_Store"],
    ),
    DeploymentTemplate(
        name="Node App",
        build_command="npm run build",
        post_deploy_command="npm ci --omit=dev",
        restart_command="systemctl restart your-app",
        ignore_patterns=["node_modules", ".git", ".env", ".DS_Store"],
    ),
]


def deployment_template(name: str) -> DeploymentTemplate:
    return next((template for template in DEPLOYMENT_TEMPLATES if template.name == name), DEPLOYMENT_TEMPLATES[0])
