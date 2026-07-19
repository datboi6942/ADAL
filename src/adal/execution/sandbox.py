import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

import structlog

from adal.config import settings

logger = structlog.get_logger(__name__)

SANDBOX_BASE = Path(tempfile.gettempdir()) / "adal_sandbox"
SANDBOX_BASE.mkdir(parents=True, exist_ok=True)

ALLOWED_IMPORTS = {
    "numpy",
    "scipy",
    "pandas",
    "matplotlib",
    "sympy",
    "astropy",
    "astroquery",
    "rdkit",
    "sklearn",
    "json",
    "csv",
    "math",
    "statistics",
    "itertools",
    "collections",
    "functools",
    "typing",
    "dataclasses",
    "pathlib",
    "os.path",
    "re",
    "decimal",
    "fractions",
    "random",
    "warnings",
    "httpx",
    "asyncio",
    "time",
    "datetime",
}

FORBIDDEN_KEYWORDS = {
    "import subprocess",
    "import shutil",
    "exec(",
    "eval(",
    "compile(",
    "__import__",
    "open(",
}


class SandboxError(Exception):
    pass


class SafetyViolationError(SandboxError):
    pass


class ExecutionTimeoutError(SandboxError):
    pass


def _audit_script(code: str) -> None:
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in code:
            raise SafetyViolationError(f"Forbidden keyword found: {keyword}")

    import_lines = [line for line in code.split("\n") if line.strip().startswith(("import ", "from "))]
    for line in import_lines:
        module_name = line.split()[1].split(".")[0] if line.startswith("import ") else line.split()[1].split(".")[0]
        if module_name not in ALLOWED_IMPORTS:
            raise SafetyViolationError(f"Import not allowed: {module_name}")


async def run_script(code: str) -> dict:
    _audit_script(code)

    sandbox_id = str(uuid.uuid4())[:8]
    sandbox_dir = SANDBOX_BASE / sandbox_id
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    script_path = sandbox_dir / "script.py"
    script_path.write_text(code)

    logger.info("sandbox_execution_start", sandbox_id=sandbox_id, code_length=len(code))

    try:
        proc = await asyncio.create_subprocess_exec(
            os.environ.get("ADAL_PYTHON_BIN", sys.executable),
            str(script_path),
            cwd=str(sandbox_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "MPLBACKEND": "Agg"},
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.sandbox_timeout,
        )

        logger.info(
            "sandbox_execution_done",
            sandbox_id=sandbox_id,
            returncode=proc.returncode,
            stdout_len=len(stdout),
            stderr_len=len(stderr),
        )

        return {
            "sandbox_id": sandbox_id,
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "success": proc.returncode == 0,
        }

    except TimeoutError:
        logger.error("sandbox_timeout", sandbox_id=sandbox_id, timeout=settings.sandbox_timeout)
        raise ExecutionTimeoutError(f"Script timed out after {settings.sandbox_timeout}s")
    finally:
        import shutil

        shutil.rmtree(sandbox_dir, ignore_errors=True)
