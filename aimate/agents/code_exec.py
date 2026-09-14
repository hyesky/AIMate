"""execute_code — 沙箱子进程代码执行工具（参考 hermes code_execution_tool.py，自研精简版）

AIMate 纯 stdlib 内网平台：把要执行的 Python 代码写进临时脚本，用独立子进程
（隔离 sys.executable 解释器）运行并回收 stdout/stderr。不在此进程内 exec，
避免污染/中断 server 主进程。约束：
  * 单次超时 DEFAULT_TIMEOUT（默认 300s，5 分钟）
  * stdout 按 MAX_STDOUT_BYTES 截断（保留头尾，标注省略字节数）
  * 子进程环境做最小清洗，不注入无关密钥
调用方（AgentRunner）把本工具注册为内置工具 execute_code，schema 由本模块提供。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from typing import Any

DEFAULT_TIMEOUT = 300          # 5 分钟（对齐 hermes）
MAX_STDOUT_BYTES = 50 * 1024   # 50KB 输出上限
MAX_STDERR_BYTES = 20 * 1024
HEAD_KEEP = 40 * 1024          # 截断时保留头部字节
TAIL_KEEP = 10 * 1024          # 截断时保留尾部字节


def execute_code(
    code: str,
    timeout: int | float = DEFAULT_TIMEOUT,
    workdir: str | None = None,
) -> dict:
    """在隔离子进程中执行 Python 代码，返回 {ok, stdout, stderr, truncated, ...}。"""
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "stdout": "", "stderr": "代码为空", "truncated": False}

    fd, path = tempfile.mkstemp(suffix=".py", prefix="aimate_exec_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        cmd = [sys.executable, path]
        env = _scrub_env(os.environ.copy())
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                cwd=workdir or os.getcwd(),
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            out = _truncate(getattr(e, "stdout", b""), MAX_STDOUT_BYTES)
            err = _truncate(getattr(e, "stderr", b""), MAX_STDERR_BYTES)
            return {
                "ok": False,
                "stdout": out[0],
                "stderr": f"[超时] 执行超过 {timeout}s 已中止。" + (("\n" + err[0]) if err[0] else ""),
                "truncated": out[1] or err[1],
                "timeout": True,
            }
        except OSError as e:
            return {"ok": False, "stdout": "", "stderr": f"无法启动子进程: {e}",
                    "truncated": False}

        out_text, out_trunc = _truncate(proc.stdout, MAX_STDOUT_BYTES)
        err_text, err_trunc = _truncate(proc.stderr, MAX_STDERR_BYTES)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": out_text,
            "stderr": err_text,
            "truncated": out_trunc or err_trunc,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _truncate(data: bytes, cap: int) -> tuple[str, bool]:
    """按字节截断，保留头尾，返回 (文本, 是否截断)。"""
    if not data:
        return "", False
    total = len(data)
    if total <= cap:
        return data.decode("utf-8", errors="replace"), False
    head = data[:HEAD_KEEP if cap > (HEAD_KEEP + TAIL_KEEP) else cap // 2]
    tail = data[-(TAIL_KEEP if cap > (HEAD_KEEP + TAIL_KEEP) else cap // 2):]
    omitted = total - len(head) - len(tail)
    text = (head.decode("utf-8", errors="replace")
            + f"\n ... [输出省略 {omitted} 字节] ...\n"
            + tail.decode("utf-8", errors="replace"))
    return text, True


def _scrub_env(env: dict[str, str]) -> dict[str, str]:
    """最小环境清洗：移除可能的密钥/代理相关项（保留基本运行所需）。"""
    for key in ("AIMATE_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "AWS_SECRET_ACCESS_KEY",
                "AWS_ACCESS_KEY_ID", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "DEEPSEEK_API_KEY", "GOOGLE_API_KEY", "HF_TOKEN"):
        env.pop(key, None)
    return env


def schema() -> dict:
    """OpenAI function schema（供 AgentRunner 注册为内置工具）。"""
    return {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码（在隔离沙箱子进程中运行，输出 stdout）",
            },
            "timeout": {
                "type": "number",
                "description": f"超时秒数（默认 {DEFAULT_TIMEOUT}，最大 600）",
            },
        },
        "required": ["code"],
    }
