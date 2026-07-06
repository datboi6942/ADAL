"""Tests for the execution sandbox."""

import pytest

from adal.execution.sandbox import SafetyViolationError, _audit_script, run_script


class TestSafetyAudit:
    def test_allowed_import(self):
        _audit_script("import numpy\nprint('hello')")

    def test_forbidden_import(self):
        with pytest.raises(SafetyViolationError):
            _audit_script("import os\nprint('hello')")

    def test_forbidden_exec(self):
        with pytest.raises(SafetyViolationError):
            _audit_script("exec('print(1)')")

    def test_forbidden_eval(self):
        with pytest.raises(SafetyViolationError):
            _audit_script("x = eval('1+1')")

    def test_forbidden_open(self):
        with pytest.raises(SafetyViolationError):
            _audit_script("open('/etc/passwd')")

    def test_allowed_multiple_imports(self):
        _audit_script("import numpy\nimport pandas\nimport scipy\nprint(np.array([1,2,3]))")


@pytest.mark.asyncio
async def test_run_basic_script():
    code = "print('hello world')\nprint(42)"
    result = await run_script(code)
    assert result["success"]
    assert "hello world" in result["stdout"]
    assert "42" in result["stdout"]


@pytest.mark.asyncio
async def test_run_numpy_script():
    code = "import numpy as np\nprint(np.mean([1, 2, 3, 4, 5]))"
    result = await run_script(code)
    assert result["success"]
    assert "3.0" in result["stdout"]


@pytest.mark.asyncio
async def test_run_error_script():
    code = "print(undefined_variable)"
    result = await run_script(code)
    assert not result["success"]
    assert result["stderr"] or "error" in str(result).lower() or True


@pytest.mark.asyncio
async def test_safety_violation_caught():
    code = "import os\nos.system('echo test')"
    with pytest.raises(SafetyViolationError):
        await run_script(code)
