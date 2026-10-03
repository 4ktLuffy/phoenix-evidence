"""Run Phoenix evaluators on the Codex CLI, with no API key: `LLM(provider='codex', model=...)`.

    import phoenix_evidence.codex  # registers the provider
    llm = LLM(provider='codex', model='gpt-5.6-luna')

Each call is one `codex exec`, with the evaluator's prompt as the task and Codex's own agent
instructions replaced (`model_instructions_file`) by a short judge instruction, so Codex answers
as a judge rather than as a coding agent. Structured output is passed as a strict JSON schema in
the evaluator's own key order: Phoenix puts `explanation` before `label`, so the judge reasons
before it decides, and sorting the keys would reverse that (judge-admissibility measured the
difference). Results record the model and reasoning effort in `model_name`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from phoenix.evals.llm.prompts import PromptLike
from phoenix.evals.llm.registries import register_adapter, register_provider
from phoenix.evals.llm.types import BaseLLMAdapter, ObjectGenerationMethod

WORKDIR = Path(tempfile.gettempdir()) / 'phoenix-evidence-codex'
INSTRUCTIONS = (
    'You are an evaluator. Read the task and answer it exactly as asked. Do not run commands, '
    'do not inspect files, and do not ask questions. Reply with the answer only.'
)


class CodexClient:
    """What `LLM(provider='codex')` builds: the model and reasoning effort for `codex exec`."""

    def __init__(self, model: str = 'gpt-5.6-luna', effort: str = 'none', timeout: float = 180) -> None:
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.tokens: list[int] = []


def _prompt_text(prompt: PromptLike) -> str:
    if isinstance(prompt, str):
        return prompt
    parts = []
    for message in prompt:
        content = message.get('content') if isinstance(message, dict) else getattr(message, 'content', '')
        if isinstance(content, list):
            content = '\n'.join(c.get('text', '') for c in content if isinstance(c, dict))
        role = message.get('role') if isinstance(message, dict) else getattr(message, 'role', 'user')
        parts.append(f'[{role}]\n{content}')
    return '\n\n'.join(parts)


def _strict(schema: Any) -> Any:
    """Codex's structured output wants every object closed and every property required."""
    if isinstance(schema, dict):
        out = {k: _strict(v) for k, v in schema.items() if k != 'title'}
        if out.get('type') == 'object' and 'properties' in out:
            out['additionalProperties'] = False
            out['required'] = list(out['properties'])
        return out
    if isinstance(schema, list):
        return [_strict(v) for v in schema]
    return schema


def _args(client: CodexClient, out_path: Path, schema_path: Path | None) -> list[str]:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    instructions = WORKDIR / 'instructions.md'
    if not instructions.exists():
        partial = instructions.with_suffix('.tmp')
        partial.write_text(INSTRUCTIONS)
        partial.replace(instructions)
    args = [
        'codex', 'exec', '-m', client.model, '-c', f'model_reasoning_effort="{client.effort}"',
        '-c', f'model_instructions_file="{instructions}"',
        '--skip-git-repo-check', '--sandbox', 'read-only', '--ephemeral', '--color', 'never',
        '-o', str(out_path),
    ]  # fmt: skip
    if schema_path is not None:
        args += ['--output-schema', str(schema_path)]
    return args


def _schema_file(schema: dict[str, Any]) -> Path:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_strict(schema))  # key order kept: explanation before label
    path = WORKDIR / f'schema-{hashlib.sha256(text.encode()).hexdigest()[:16]}.json'
    if not path.exists():
        path.write_text(text)
    return path


def _record_tokens(client: CodexClient, log: str) -> None:
    if 'tokens used' in log:
        try:
            client.tokens.append(int(log.split('tokens used', 1)[1].split()[0].replace(',', '')))
        except ValueError:
            pass


async def _run(client: CodexClient, prompt: str, schema: dict[str, Any] | None) -> str:
    with tempfile.NamedTemporaryFile(dir=WORKDIR if WORKDIR.exists() else None, suffix='.out', delete=False) as f:
        out_path = Path(f.name)
    args = _args(client, out_path, _schema_file(schema) if schema else None)
    process = await asyncio.create_subprocess_exec(
        *args, prompt, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, cwd=WORKDIR,
    )  # fmt: skip
    try:
        log, _ = await asyncio.wait_for(process.communicate(), client.timeout)
    except asyncio.TimeoutError:  # the builtin TimeoutError only from 3.11
        process.kill()
        raise
    text = log.decode(errors='replace')
    _record_tokens(client, text)
    if process.returncode != 0:
        raise RuntimeError(f'codex exited {process.returncode}: {text[-300:]}')
    reply = out_path.read_text()
    out_path.unlink(missing_ok=True)
    return reply


def _run_sync(client: CodexClient, prompt: str, schema: dict[str, Any] | None) -> str:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=WORKDIR, suffix='.out', delete=False) as f:
        out_path = Path(f.name)
    args = _args(client, out_path, _schema_file(schema) if schema else None)
    done = subprocess.run(
        [*args, prompt], stdin=subprocess.DEVNULL, capture_output=True, cwd=WORKDIR, timeout=client.timeout
    )
    text = (done.stdout + done.stderr).decode(errors='replace')
    _record_tokens(client, text)
    if done.returncode != 0:
        raise RuntimeError(f'codex exited {done.returncode}: {text[-300:]}')
    reply = out_path.read_text()
    out_path.unlink(missing_ok=True)
    return reply


def _create_client(model: str = 'gpt-5.6-luna', is_async: bool = False, **kwargs: Any) -> CodexClient:
    # One client serves both: every call is a separate `codex exec` process.
    return CodexClient(model=model, **kwargs)


@register_adapter(identifier=lambda client: isinstance(client, CodexClient), name='codex')
@register_provider(provider='codex', client_factory=_create_client)
class CodexAdapter(BaseLLMAdapter):
    client: CodexClient

    @classmethod
    def client_name(cls) -> str:
        return 'codex'

    def generate_text(self, prompt: PromptLike, **kwargs: Any) -> str:
        return _run_sync(self.client, _prompt_text(prompt), None)

    async def async_generate_text(self, prompt: PromptLike, **kwargs: Any) -> str:
        return await _run(self.client, _prompt_text(prompt), None)

    def generate_object(
        self,
        prompt: PromptLike,
        schema: dict[str, Any],
        method: ObjectGenerationMethod = ObjectGenerationMethod.AUTO,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return json.loads(_run_sync(self.client, _prompt_text(prompt), schema))

    async def async_generate_object(
        self,
        prompt: PromptLike,
        schema: dict[str, Any],
        method: ObjectGenerationMethod = ObjectGenerationMethod.AUTO,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return json.loads(await _run(self.client, _prompt_text(prompt), schema))

    @property
    def model_name(self) -> str:
        return f'codex:{self.client.model}@{self.client.effort}'
