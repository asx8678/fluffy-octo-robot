"""Skills tools - dedicated tools for Agent Skills integration."""

import asyncio
import logging
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import RunContext

from code_muse.callbacks import register_callback
from code_muse.config import get_global_model_name
from code_muse.messaging import (
    SkillActivateMessage,
    SkillBackgroundMessage,
    SkillDeactivateMessage,
    SkillEntry,
    SkillListMessage,
    get_message_bus,
)
from code_muse.plugins.agent_skills.register_callbacks import _deactivated_skills

logger = logging.getLogger(__name__)

# Background job store: job_id -> metadata dict
_background_jobs: dict[str, dict] = {}


# Output models
class SkillListOutput(BaseModel):
    """Output for list_or_search_skills tool."""

    skills: list[dict]  # Each has: name, description, path, tags
    total_count: int
    query: str | None = None  # The search query if provided
    error: str | None = None


class SkillActivateOutput(BaseModel):
    """Output for activate_skill tool."""

    skill_name: str
    content: str  # Full SKILL.md content
    resources: list[str]  # Available resource files
    error: str | None = None
    consent_required: bool = False
    message: str = ""


def register_activate_skill(agent):
    """Register the activate_skill tool."""

    @agent.tool
    async def activate_skill(
        context: RunContext,
        skill_name: str = "",
        consent_confirmed: bool = False,
    ) -> SkillActivateOutput:
        """Activate a skill by loading its full SKILL.md instructions."""
        # Import from plugin

        from code_muse.plugins.agent_skills.config import (
            get_skill_directories,
            get_skills_enabled,
        )
        from code_muse.plugins.agent_skills.discovery import discover_skills
        from code_muse.plugins.agent_skills.metadata import (
            get_skill_resources,
            load_full_skill_content,
        )

        # Check if skills enabled
        if not get_skills_enabled():
            return SkillActivateOutput(
                skill_name=skill_name,
                content="",
                resources=[],
                error="Skills integration is disabled. Enable it with /set skills_enabled=true",
            )

        # Discover skills
        try:
            skill_dirs = get_skill_directories()
            discovered = discover_skills(skill_dirs)
        except Exception as e:
            logger.error(f"Failed to discover skills: {e}")
            return SkillActivateOutput(
                skill_name=skill_name,
                content="",
                resources=[],
                error=f"Failed to discover skills: {e}",
            )

        # Find skill by name
        skill_path = None
        for skill_info in discovered:
            if skill_info.name == skill_name and skill_info.has_skill_md:
                skill_path = skill_info.path
                break

        if not skill_path:
            return SkillActivateOutput(
                skill_name=skill_name,
                content="",
                resources=[],
                error=f"Skill '{skill_name}' not found. Use list_or_search_skills to see available skills.",
            )

        # Consent gating
        if not consent_confirmed:
            return SkillActivateOutput(
                skill_name=skill_name,
                content="",
                resources=[],
                error=None,
                consent_required=True,
                message=f"To activate '{skill_name}', please ask the user: 'May I activate the {skill_name} skill?' and call activate_skill again with consent_confirmed=True after they agree.",
            )

        # Load full content
        content = load_full_skill_content(skill_path)
        if content is None:
            return SkillActivateOutput(
                skill_name=skill_name,
                content="",
                resources=[],
                error=f"Failed to load content for skill '{skill_name}'",
            )

        # Get resource list
        resource_paths = get_skill_resources(skill_path)
        resources = [str(p) for p in resource_paths]

        # Emit message for UI
        content_preview = content[:200] if content else ""
        skill_msg = SkillActivateMessage(
            skill_name=skill_name,
            skill_path=str(skill_path),
            content_preview=content_preview,
            resource_count=len(resources),
            success=True,
        )
        get_message_bus().emit(skill_msg)

        return SkillActivateOutput(
            skill_name=skill_name,
            content=content,
            resources=resources,
            error=None,
        )

    return activate_skill


def register_list_or_search_skills(agent):
    """Register the list_or_search_skills tool."""

    @agent.tool
    async def list_or_search_skills(
        context: RunContext, query: str | None = None
    ) -> SkillListOutput:
        """List available skills, optionally filtered by search query.

        Args:
            query: Optional search term to filter skills by name/description/tags.
                   If None, returns all available skills.
        """
        # Import from plugin

        from code_muse.plugins.agent_skills.config import (
            get_disabled_skills,
            get_skill_directories,
            get_skills_enabled,
        )
        from code_muse.plugins.agent_skills.discovery import discover_skills
        from code_muse.plugins.agent_skills.metadata import parse_skill_metadata

        # Check if skills enabled
        if not get_skills_enabled():
            return SkillListOutput(
                skills=[],
                total_count=0,
                query=query,
                error="Skills integration is disabled. Enable it with /set skills_enabled=true",
            )

        # Get disabled skills
        disabled_skills = get_disabled_skills()

        # Discover all skills
        try:
            skill_dirs = get_skill_directories()
            discovered = discover_skills(skill_dirs)
        except Exception as e:
            logger.error(f"Failed to discover skills: {e}")
            return SkillListOutput(
                skills=[],
                total_count=0,
                query=query,
                error=f"Failed to discover skills: {e}",
            )

        # Parse metadata for each skill
        skills_list = []
        for skill_info in discovered:
            # Skip disabled skills
            if skill_info.name in disabled_skills:
                continue

            # Only include skills with valid SKILL.md
            if not skill_info.has_skill_md:
                continue

            metadata = parse_skill_metadata(skill_info.path)
            if metadata:
                skill_dict = {
                    "name": metadata.name,
                    "description": metadata.description,
                    "path": str(metadata.path),
                    "tags": metadata.tags,
                    "version": metadata.version,
                    "author": metadata.author,
                    "source": metadata.source or skill_info.source,
                    "trust": metadata.trust or skill_info.trust,
                    "hash": metadata.skill_md_hash or skill_info.skill_md_hash,
                }
                # Filter out None values for cleanliness
                skill_dict = {k: v for k, v in skill_dict.items() if v is not None}
                skills_list.append(skill_dict)

        # Filter by query if provided
        if query:
            query_lower = query.lower()
            filtered = []
            for skill in skills_list:
                # Check name (case-insensitive)
                if query_lower in skill["name"].lower():
                    filtered.append(skill)
                    continue

                # Check description (case-insensitive)
                if query_lower in skill["description"].lower():
                    filtered.append(skill)
                    continue

                # Check tags (case-insensitive)
                for tag in skill["tags"]:
                    if query_lower in tag.lower():
                        filtered.append(skill)
                        break
            skills_list = filtered

        # Emit message for UI
        skill_entries = [
            SkillEntry(
                name=s["name"],
                description=s["description"],
                path=s["path"],
                tags=s["tags"],
                enabled=s["name"] not in disabled_skills,
            )
            for s in skills_list
        ]
        skill_msg = SkillListMessage(
            skills=skill_entries,
            query=query,
            total_count=len(skills_list),
        )
        get_message_bus().emit(skill_msg)

        return SkillListOutput(
            skills=skills_list, total_count=len(skills_list), query=query, error=None
        )

    return list_or_search_skills


# Output models for new tools
class SkillDeactivateOutput(BaseModel):
    """Output for deactivate_skill tool."""

    skill_name: str
    success: bool
    message: str


class SkillBackgroundOutput(BaseModel):
    """Output for background skill job tools."""

    job_id: str
    skill_name: str
    status: str  # "started" | "running" | "complete" | "error"
    result: str = ""
    log_file: str = ""


def register_deactivate_skill(agent):
    """Register the deactivate_skill tool."""

    @agent.tool
    async def deactivate_skill(
        context: RunContext, skill_name: str = ""
    ) -> SkillDeactivateOutput:
        """Deactivate a skill so it is excluded from prompt injection."""
        _deactivated_skills.add(skill_name)
        message = f"Skill '{skill_name}' has been deactivated for this session."
        skill_msg = SkillDeactivateMessage(
            skill_name=skill_name, success=True, message=message
        )
        get_message_bus().emit(skill_msg)
        return SkillDeactivateOutput(
            skill_name=skill_name, success=True, message=message
        )

    return deactivate_skill


def register_run_skill_background(agent):
    """Register the run_skill_background tool."""

    @agent.tool
    async def run_skill_background(
        context: RunContext, skill_name: str = "", task: str = ""
    ) -> SkillBackgroundOutput:
        """Launch a headless background agent with a skill as system prompt."""
        from code_muse.plugins.agent_skills.config import (
            get_skill_directories,
            get_skills_enabled,
        )
        from code_muse.plugins.agent_skills.discovery import discover_skills
        from code_muse.plugins.agent_skills.metadata import (
            load_full_skill_content,
            parse_yaml_frontmatter,
        )

        if not get_skills_enabled():
            return SkillBackgroundOutput(
                job_id="",
                skill_name=skill_name,
                status="error",
                result="Skills integration is disabled.",
                log_file="",
            )

        try:
            skill_dirs = get_skill_directories()
            discovered = discover_skills(skill_dirs)
        except Exception as e:
            logger.error(f"Failed to discover skills: {e}")
            return SkillBackgroundOutput(
                job_id="",
                skill_name=skill_name,
                status="error",
                result=f"Failed to discover skills: {e}",
                log_file="",
            )

        skill_path = None
        for skill_info in discovered:
            if skill_info.name == skill_name and skill_info.has_skill_md:
                skill_path = skill_info.path
                break

        if not skill_path:
            return SkillBackgroundOutput(
                job_id="",
                skill_name=skill_name,
                status="error",
                result=f"Skill '{skill_name}' not found.",
                log_file="",
            )

        content = load_full_skill_content(skill_path)
        if content is None:
            return SkillBackgroundOutput(
                job_id="",
                skill_name=skill_name,
                status="error",
                result=f"Failed to load content for skill '{skill_name}'.",
                log_file="",
            )

        # Parse frontmatter for worktree flag
        frontmatter = parse_yaml_frontmatter(content)
        use_worktree = bool(frontmatter and frontmatter.get("worktree"))

        # Prepare ephemeral worktree / cwd
        if use_worktree:
            worktree_dir = tempfile.mkdtemp(prefix=f"skill_bg_{skill_name}_")
            # Attempt git worktree if inside a git repo
            try:
                git_proc = await asyncio.create_subprocess_exec(
                    "git",
                    "rev-parse",
                    "--show-toplevel",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                git_stdout, _ = await git_proc.communicate()
                if git_proc.returncode != 0:
                    raise subprocess.CalledProcessError(
                        git_proc.returncode, ["git", "rev-parse", "--show-toplevel"]
                    )
                git_root = git_stdout.decode().strip()
                branch_name = f"skill-bg-{uuid.uuid4().hex[:8]}"
                worktree_proc = await asyncio.create_subprocess_exec(
                    "git",
                    "worktree",
                    "add",
                    worktree_dir,
                    "-b",
                    branch_name,
                    cwd=git_root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await worktree_proc.wait()
                if worktree_proc.returncode != 0:
                    raise subprocess.CalledProcessError(
                        worktree_proc.returncode,
                        ["git", "worktree", "add", worktree_dir, "-b", branch_name],
                    )
            except Exception:
                # Fallback: just use the temp dir as plain cwd
                pass
            cwd = worktree_dir
        else:
            cwd = Path.cwd()

        # Write skill content and task to temp files
        skill_content_file = tempfile.mktemp(
            prefix=f"skill_{skill_name}_", suffix=".md"
        )
        Path(skill_content_file).write_text(content, encoding="utf-8")

        task_file = tempfile.mktemp(prefix="skill_task_", suffix=".txt")
        Path(task_file).write_text(task, encoding="utf-8")

        job_id = uuid.uuid4().hex[:8]
        # TODO: PEP 750 t-string — use templatelib when stable
        log_file = f"/tmp/skill_bg_{job_id}.log"

        # Build and launch command
        model = get_global_model_name() or "gemini"
        cmd = (
            # TODO: PEP 750 t-string — use templatelib when stable
            f"cat {shlex.quote(task_file)} | code-muse --headless "
            # TODO: PEP 750 t-string — use templatelib when stable
            f"--system-prompt {shlex.quote(skill_content_file)} "
            # TODO: PEP 750 t-string — use templatelib when stable
            f"--model {shlex.quote(model)} --cwd {shlex.quote(str(cwd))} "
            # TODO: PEP 750 t-string — use templatelib when stable
            f"> {shlex.quote(log_file)} 2>&1"
        )

        try:
            process = subprocess.Popen(cmd, shell=True, cwd=cwd)
        except Exception as e:
            return SkillBackgroundOutput(
                job_id=job_id,
                skill_name=skill_name,
                status="error",
                result=f"Failed to start background job: {e}",
                log_file=log_file,
            )

        _background_jobs[job_id] = {
            "process": process,
            "log_file": log_file,
            "skill_name": skill_name,
            "task": task,
            "skill_content_file": skill_content_file,
            "task_file": task_file,
            "cwd": cwd,
        }

        bus_msg = SkillBackgroundMessage(
            job_id=job_id,
            skill_name=skill_name,
            status="started",
            result="",
            log_file=log_file,
        )
        get_message_bus().emit(bus_msg)

        return SkillBackgroundOutput(
            job_id=job_id,
            skill_name=skill_name,
            status="started",
            result="Background job started.",
            log_file=log_file,
        )

    return run_skill_background


def register_check_skill_background(agent):
    """Register the check_skill_background tool."""

    @agent.tool
    async def check_skill_background(
        context: RunContext, job_id: str = ""
    ) -> SkillBackgroundOutput:
        """Check the status of a background skill job."""
        job = _background_jobs.get(job_id)
        if not job:
            return SkillBackgroundOutput(
                job_id=job_id,
                skill_name="",
                status="error",
                result=f"Job '{job_id}' not found.",
                log_file="",
            )

        process = job["process"]
        log_file = job["log_file"]
        skill_name = job["skill_name"]

        poll_result = process.poll()
        if poll_result is None:
            return SkillBackgroundOutput(
                job_id=job_id,
                skill_name=skill_name,
                status="running",
                result="Job is still running.",
                log_file=log_file,
            )

        # Process finished – read log
        try:
            result_text = Path(log_file).read_text(encoding="utf-8")
        except Exception:
            result_text = ""

        status = "complete" if poll_result == 0 else "error"
        return SkillBackgroundOutput(
            job_id=job_id,
            skill_name=skill_name,
            status=status,
            result=result_text,
            log_file=log_file,
        )

    return check_skill_background


def _cleanup_skill_temp_files() -> None:
    """Clean up background skill jobs and temp files on shutdown."""
    count = len(_background_jobs)
    if not count:
        return

    for _job_id, job in list(_background_jobs.items()):
        process = job.get("process")
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass

        cwd = job.get("cwd")
        if cwd and "skill_bg_" in str(cwd):
            shutil.rmtree(cwd, ignore_errors=True)

        skill_content_file = job.get("skill_content_file")
        if skill_content_file and Path(skill_content_file).exists():
            Path(skill_content_file).unlink(missing_ok=True)

        task_file = job.get("task_file")
        if task_file and Path(task_file).exists():
            Path(task_file).unlink(missing_ok=True)

    _background_jobs.clear()
    logger.info("Cleaned up %s background skill job(s)", count)


register_callback("shutdown", _cleanup_skill_temp_files)
