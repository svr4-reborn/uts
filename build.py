#!/usr/bin/env python3

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by runtime setup, not tests.
    yaml = None


DEFAULT_UTS_CONFIG = Path('uts/build-specs/i386/kernel.yaml')
MERGEABLE_BUILD_SPEC_SECTIONS = (
    'toolchain',
    'variables',
    'profiles',
    'source_views',
    'targets',
)


class BuildSpecError(RuntimeError):
    pass


def _empty_string_list() -> list[str]:
    return []


@dataclasses.dataclass(frozen=True)
class Toolchain:
    cc: str = 'gcc'
    cpp: str = 'cpp'
    ld: str = 'ld'
    cflags: list[str] = dataclasses.field(default_factory=_empty_string_list)
    cppflags: list[str] = dataclasses.field(default_factory=_empty_string_list)
    ldflags: list[str] = dataclasses.field(default_factory=_empty_string_list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> 'Toolchain':
        return cls(
            cc=str(raw.get('cc', 'gcc')),
            cpp=str(raw.get('cpp', 'cpp')),
            ld=str(raw.get('ld', 'ld')),
            cflags=_string_list(raw.get('cflags', []), 'toolchain.cflags'),
            cppflags=_string_list(raw.get('cppflags', []), 'toolchain.cppflags'),
            ldflags=_string_list(raw.get('ldflags', []), 'toolchain.ldflags'),
        )


@dataclasses.dataclass(frozen=True)
class BuildPlan:
    toolchain: Toolchain
    variables: dict[str, str]
    profiles: dict[str, dict[str, Any]]
    source_views: dict[str, dict[str, Any]]
    targets: dict[str, dict[str, Any]]


@dataclasses.dataclass(frozen=True)
class CompileCommand:
    directory: str
    file: str
    arguments: list[str]
    output: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'directory': self.directory,
            'file': self.file,
            'arguments': self.arguments,
        }
        if self.output is not None:
            payload['output'] = self.output
        return payload


class BuildRunner:
    def __init__(self, workspace_root: Path, builddir: Path, toolchain: Toolchain, variables: dict[str, str], profiles: dict[str, dict[str, Any]], source_views: dict[str, dict[str, Any]], dry_run: bool = False, parallel_enabled: bool = True, compile_commands_path: Path | None = None):
        self.workspace_root = workspace_root
        self.builddir = builddir
        self.toolchain = toolchain
        self.profiles = profiles
        self.source_views = source_views
        self.dry_run = dry_run
        self.parallel_enabled = parallel_enabled
        self.compile_commands_path = compile_commands_path
        self.compile_commands: list[CompileCommand] = []
        self.failures: list[str] = []
        self.variables = {
            'workspace_root': str(self.workspace_root),
            'kernel_root': str((self.workspace_root / 'uts').resolve()),
            'builddir': str(self.builddir),
            'cc': self.toolchain.cc,
            'cpp': self.toolchain.cpp,
            'ld': self.toolchain.ld,
        }
        self._merge_variables(variables)

    def run_target(self, targets: dict[str, dict[str, Any]], target_name: str) -> None:
        order = self._resolve_target_order(targets, target_name)
        for name in order:
            target = targets[name]
            description = str(target.get('description', '')).strip()
            if description:
                print(f'==> {name}: {description}')
            else:
                print(f'==> {name}')
            for index, step in enumerate(_step_list(target), start=1):
                self._run_step(name, index, step)
        if self.failures:
            preview = '; '.join(self.failures[:5])
            if len(self.failures) > 5:
                preview = f'{preview}; ...'
            raise BuildSpecError(f'Build completed with {len(self.failures)} recorded failures: {preview}')

    def write_compile_commands(self) -> None:
        if self.compile_commands_path is None:
            return
        self.compile_commands_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [entry.as_dict() for entry in self.compile_commands]
        self.compile_commands_path.write_text(f'{json.dumps(payload, indent=2)}\n', encoding='utf-8')
        print(f'Wrote {len(payload)} compile commands to {self.compile_commands_path}')

    def _resolve_target_order(self, targets: dict[str, dict[str, Any]], target_name: str) -> list[str]:
        order: list[str] = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise BuildSpecError(f'Cyclic target dependency detected at {name}')
            target = targets.get(name)
            if target is None:
                raise BuildSpecError(f'Unknown target: {name}')
            visiting.add(name)
            for dependency in _string_list(target.get('depends_on', []), f'targets.{name}.depends_on'):
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            order.append(name)

        visit(target_name)
        return order

    def _run_step(self, target_name: str, step_index: int, step: dict[str, Any]) -> None:
        kind = str(step.get('kind', '')).strip()
        if not kind:
            raise BuildSpecError(f'targets.{target_name}.steps[{step_index}] is missing kind')

        if kind == 'mkdir':
            path = self._resolve_path(_required_string(step, 'path'))
            print(f'  [{step_index}] mkdir {path}')
            if not self.dry_run:
                path.mkdir(parents=True, exist_ok=True)
            return

        if kind == 'mkdirs':
            for raw_path in _string_list(step.get('paths', []), 'mkdirs.paths'):
                path = self._resolve_path(raw_path)
                print(f'  [{step_index}] mkdir {path}')
                if not self.dry_run:
                    path.mkdir(parents=True, exist_ok=True)
            return

        if kind == 'remove-path':
            path = self._resolve_path(_required_string(step, 'path'))
            print(f'  [{step_index}] remove {path}')
            if not self.dry_run and path.exists():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            return

        if kind == 'copy-tree':
            source = self._resolve_path(_required_string(step, 'source'))
            destination = self._resolve_path(_required_string(step, 'destination'))
            print(f'  [{step_index}] copy-tree {source} -> {destination}')
            if not self.dry_run:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination, dirs_exist_ok=True)
            return

        if kind == 'preprocess':
            self._run_preprocess_step(step_index, step)
            return

        if kind == 'preprocess-batch':
            self._run_preprocess_batch_step(step_index, step)
            return

        if kind == 'compile':
            self._run_compile_step(step_index, step)
            return

        if kind == 'compile-bundle':
            self._run_compile_bundle_step(step_index, step)
            return

        if kind == 'link':
            self._run_link_step(step_index, step)
            return

        if kind == 'command':
            self._run_command_step(step_index, step)
            return

        raise BuildSpecError(f'Unsupported step kind: {kind}')

    def _run_preprocess_step(self, step_index: int, step: dict[str, Any]) -> None:
        source_path = self._resolve_source_path(step, _required_string(step, 'source'))
        cwd = source_path.parent if self._uses_source_view(step) else self._resolve_cwd(step)
        source = source_path.name if self._uses_source_view(step) else self._resolve_text(_required_string(step, 'source'))
        output = self._resolve_path(_required_string(step, 'output'))
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._resolve_tool(step, 'tool', self.toolchain.cpp),
            *self.toolchain.cppflags,
            *self._source_view_include_args(step),
            *self._resolve_step_args(step, 'flags', 'preprocess.flags'),
            source,
            '-o',
            str(output),
        ]
        self._run_command(command, cwd=cwd, env=self._resolve_env(step), step_index=step_index, continue_on_error=self._should_continue_on_error(step))

    def _run_preprocess_batch_step(self, step_index: int, step: dict[str, Any]) -> None:
        output_dir = self._resolve_optional_path(step.get('output_dir'))
        suffix = str(step.get('suffix', '.i'))
        entries = _mapping_list(step.get('files', []), 'preprocess-batch.files')
        if not entries and step.get('discover') is not None:
            entries = [{'source': source} for source in self._discover_sources(step, 'preprocess-batch.discover')]
        for entry in entries:
            entry_step = dict(step)
            entry_step.update(entry)
            entry_step.pop('files', None)
            entry_step.pop('output_dir', None)
            entry_step.pop('suffix', None)
            entry_step.pop('discover', None)
            if 'output' not in entry_step:
                if output_dir is None:
                    raise BuildSpecError('preprocess-batch requires output_dir or per-file output')
                source = self._resolve_text(_required_string(entry_step, 'source'))
                entry_step['output'] = str(output_dir / Path(source).with_suffix(suffix))
            self._run_preprocess_step(step_index, entry_step)

    def _run_compile_step(self, step_index: int, step: dict[str, Any]) -> None:
        self._compile_objects(step_index, step)

    def _run_compile_bundle_step(self, step_index: int, step: dict[str, Any]) -> None:
        outputs, had_failures = self._compile_objects(step_index, step)
        if had_failures:
            print(f'  [{step_index}] skipping link because one or more object builds failed')
            return
        link_step: dict[str, Any] = {
            'cwd': step.get('link_cwd'),
            'linker': step.get('linker'),
            'use': step.get('link_use', []),
            'env': step.get('env', {}),
            'continue_on_error': step.get('continue_on_error'),
            'inputs': [str(output) for output in outputs],
            'flags': step.get('link_flags', []),
            'output': _required_string(step, 'output'),
        }
        self._run_link_step(step_index, link_step)

    def _run_link_step(self, step_index: int, step: dict[str, Any]) -> None:
        cwd = self._resolve_cwd(step)
        linker = self._resolve_tool(step, 'linker', self.toolchain.ld)
        output = self._resolve_path(_required_string(step, 'output'))
        output.parent.mkdir(parents=True, exist_ok=True)
        inputs = [str(self._resolve_path(value)) for value in _string_list(step.get('inputs', []), 'link.inputs')]
        flags = [*self.toolchain.ldflags, *self._resolve_step_args(step, 'flags', 'link.flags')]
        command = [linker, *flags, *inputs, '-o', str(output)]
        self._run_command(command, cwd=cwd, env=self._resolve_env(step), step_index=step_index, continue_on_error=self._should_continue_on_error(step))

    def _run_command_step(self, step_index: int, step: dict[str, Any]) -> None:
        cwd = self._resolve_cwd(step)
        command = self._resolve_args(step.get('argv', []), 'command.argv')
        self._run_command(command, cwd=cwd, env=self._resolve_env(step), step_index=step_index, continue_on_error=self._should_continue_on_error(step))

    def _run_command(self, command: list[str], cwd: Path, env: dict[str, str], step_index: int, continue_on_error: bool = False) -> bool:
        rendered = ' '.join(shlex.quote(part) for part in command)
        print(f'  [{step_index}] {rendered}')
        if self.dry_run:
            return True
        try:
            subprocess.run(command, cwd=cwd, env=env, check=True)
        except subprocess.CalledProcessError:
            if continue_on_error:
                self.failures.append(f'{cwd}: {rendered}')
                print(f'  [{step_index}] command failed but continuing')
                return False
            raise
        return True

    def _resolve_cwd(self, step: dict[str, Any]) -> Path:
        raw_cwd = self._step_scalar(step, 'cwd')
        if raw_cwd is None:
            return self.workspace_root
        return self._resolve_path(str(raw_cwd))

    def _resolve_env(self, step: dict[str, Any]) -> dict[str, str]:
        env = dict(os.environ)
        for profile in self._step_profiles(step):
            self._merge_env_mapping(env, profile.get('env', {}), 'profile env')
        self._merge_env_mapping(env, step.get('env', {}), 'step env')
        return env

    def _resolve_text(self, value: str) -> str:
        try:
            return value.format_map(self.variables)
        except KeyError as exc:
            raise BuildSpecError(f'Unknown variable {exc.args[0]!r} in {value!r}') from exc

    def _resolve_path(self, value: str) -> Path:
        resolved = Path(self._resolve_text(value))
        if resolved.is_absolute():
            return resolved
        return self.workspace_root / resolved

    def _resolve_optional_path(self, value: Any) -> Path | None:
        if value is None:
            return None
        return self._resolve_path(str(value))

    def _source_view_include_args(self, step: dict[str, Any]) -> list[str]:
        include_roots = self._step_scalar(step, 'include_source_view_roots')
        if include_roots is None:
            return []
        if not _bool_value(include_roots, 'include_source_view_roots'):
            return []

        roots = self._source_view_roots(step)
        return [f'-I{root}' for root in roots]

    def _uses_source_view(self, step: dict[str, Any]) -> bool:
        return self._step_scalar(step, 'source_view') is not None

    def _resolve_source_path(self, step: dict[str, Any], source: str) -> Path:
        source_view_name = self._step_scalar(step, 'source_view')
        if source_view_name is None:
            resolved = Path(self._resolve_text(source))
            if resolved.is_absolute():
                return resolved
            return self._resolve_cwd(step) / resolved

        roots = self._source_view_roots(step)
        logical_cwd = Path(str(self._step_scalar(step, 'cwd') or '.'))
        logical_source = Path(self._resolve_text(source))

        for root in roots:
            candidate = root / logical_cwd / logical_source
            if candidate.exists():
                return candidate.resolve()

        rendered_candidates = ', '.join(str(root / logical_cwd / logical_source) for root in roots)
        raise BuildSpecError(f'Unable to resolve source {source!r} in source_view {source_view_name!r}. Tried: {rendered_candidates}')

    def _source_view_roots(self, step: dict[str, Any]) -> list[Path]:
        source_view_name = self._step_scalar(step, 'source_view')
        if source_view_name is None:
            return []

        source_view = self.source_views.get(str(source_view_name))
        if source_view is None:
            raise BuildSpecError(f'Unknown source_view: {source_view_name}')

        raw_roots = source_view.get('roots', [])
        return [self._resolve_path(root) for root in _string_list(raw_roots, f'source_views.{source_view_name}.roots')]

    def _resolve_args(self, values: Any, field_name: str) -> list[str]:
        return [self._resolve_text(value) for value in _string_list(values, field_name)]

    def _should_continue_on_error(self, step: dict[str, Any]) -> bool:
        raw_value = self._step_scalar(step, 'continue_on_error')
        if raw_value is None:
            return False
        return _bool_value(raw_value, 'continue_on_error')

    def _step_parallel_workers(self, step: dict[str, Any]) -> int:
        if not self.parallel_enabled:
            return 1

        raw_parallel = self._step_scalar(step, 'parallel')
        raw_jobs = self._step_scalar(step, 'jobs')

        if raw_parallel is not None and not _bool_value(raw_parallel, 'parallel'):
            return 1

        if raw_jobs is not None:
            return _positive_int_value(raw_jobs, 'jobs')

        if raw_parallel is None:
            return 1

        return max(1, os.cpu_count() or 1)

    def _discover_sources(self, step: dict[str, Any], field_name: str) -> list[str]:
        raw_discover = step.get('discover')
        if not isinstance(raw_discover, dict):
            raise BuildSpecError(f'{field_name} must be a mapping')

        typed_discover = cast(dict[str, Any], raw_discover)
        extensions = set(_string_list(typed_discover.get('extensions', ['.c']), f'{field_name}.extensions'))
        exclude_files = set(_string_list(typed_discover.get('exclude_files', []), f'{field_name}.exclude_files'))
        exclude_dirs = set(_string_list(typed_discover.get('exclude_dirs', []), f'{field_name}.exclude_dirs'))
        recursive = _bool_value(typed_discover.get('recursive', False), f'{field_name}.recursive')

        seen: set[str] = set()
        discovered: list[str] = []
        logical_cwd = Path(str(self._step_scalar(step, 'cwd') or '.'))
        for root in self._source_view_roots(step):
            base = root / logical_cwd
            if not base.exists() or not base.is_dir():
                continue
            iterator = base.rglob('*') if recursive else base.iterdir()
            for candidate in iterator:
                if candidate.is_dir():
                    continue
                relative = candidate.relative_to(base).as_posix()
                if any(part in exclude_dirs for part in Path(relative).parts[:-1]):
                    continue
                if relative in exclude_files or candidate.name in exclude_files:
                    continue
                if candidate.suffix not in extensions:
                    continue
                if relative in seen:
                    continue
                seen.add(relative)
                discovered.append(relative)
        return sorted(discovered)

    def _resolve_step_args(self, step: dict[str, Any], field_name: str, error_field_name: str) -> list[str]:
        flags: list[str] = []
        for profile in self._step_profiles(step):
            flags.extend(self._resolve_args(profile.get(field_name, []), f'profile.{field_name}'))
        flags.extend(self._resolve_args(step.get(field_name, []), error_field_name))
        return flags

    def _resolve_tool(self, step: dict[str, Any], key: str, default: str) -> str:
        value = self._step_scalar(step, key)
        if value is None:
            return self._resolve_text(default)
        return self._resolve_text(str(value))

    def _step_scalar(self, step: dict[str, Any], key: str) -> Any:
        value: Any = None
        found = False
        for profile in self._step_profiles(step):
            if key in profile:
                value = profile[key]
                found = True
        if key in step:
            value = step[key]
            found = True
        if found:
            return value
        return None

    def _step_profiles(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        raw_use = step.get('use', [])
        if isinstance(raw_use, str):
            profile_names = [raw_use]
        elif isinstance(raw_use, list):
            profile_names = [str(name) for name in cast(list[Any], raw_use)]
        elif raw_use is None:
            profile_names = []
        else:
            raise BuildSpecError('step use must be a string or list')

        profiles: list[dict[str, Any]] = []
        for name in profile_names:
            profile = self.profiles.get(name)
            if profile is None:
                raise BuildSpecError(f'Unknown profile: {name}')
            profiles.append(profile)
        return profiles

    def _merge_env_mapping(self, env: dict[str, str], raw_env: Any, field_name: str) -> None:
        if raw_env is None:
            return
        if not isinstance(raw_env, dict):
            raise BuildSpecError(f'{field_name} must be a mapping')
        typed_env = cast(dict[Any, Any], raw_env)
        for key, value in typed_env.items():
            env[str(key)] = self._resolve_text(str(value))

    def _compile_objects(self, step_index: int, step: dict[str, Any]) -> tuple[list[Path], bool]:
        output_dir = self._resolve_path(_required_string(step, 'output_dir'))
        output_dir.mkdir(parents=True, exist_ok=True)
        compiler = self._resolve_tool(step, 'compiler', self.toolchain.cc)
        flags = [*self.toolchain.cflags, *self._source_view_include_args(step), *self._resolve_step_args(step, 'flags', 'compile.flags')]

        sources = _string_list(step.get('sources', []), 'compile.sources')
        if not sources and step.get('discover') is not None:
            sources = self._discover_sources(step, 'compile.discover')

        outputs: list[Path] = []
        had_failures = False
        continue_on_error = self._should_continue_on_error(step)
        env = self._resolve_env(step)
        compile_jobs: list[tuple[int, list[str], Path, Path]] = []
        for index, source in enumerate(sources):
            source_path = self._resolve_source_path(step, source)
            cwd = source_path.parent if self._uses_source_view(step) else self._resolve_cwd(step)
            resolved_source = source_path.name if self._uses_source_view(step) else self._resolve_text(source)
            output = output_dir / Path(source).with_suffix('.o')
            output.parent.mkdir(parents=True, exist_ok=True)
            command = [compiler, *flags, '-c', resolved_source, '-o', str(output)]
            self._record_compile_command(cwd=cwd, source_path=source_path, compiler=compiler, flags=flags, output=output)
            compile_jobs.append((index, command, cwd, output))

        workers = min(len(compile_jobs), self._step_parallel_workers(step))
        if workers > 1:
            print(f'  [{step_index}] running {len(compile_jobs)} compile commands with {workers} workers')

        def run_compile(job: tuple[int, list[str], Path, Path]) -> tuple[int, Path, bool]:
            index, command, cwd, output = job
            success = self._run_command(command, cwd=cwd, env=env, step_index=step_index, continue_on_error=continue_on_error)
            return index, output, success

        if workers <= 1:
            for job in compile_jobs:
                _, output, success = run_compile(job)
                if success:
                    outputs.append(output)
                else:
                    had_failures = True
            return outputs, had_failures

        indexed_outputs: dict[int, Path] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_job = {executor.submit(run_compile, job): job for job in compile_jobs}
            try:
                for future in concurrent.futures.as_completed(future_to_job):
                    index, output, success = future.result()
                    if success:
                        indexed_outputs[index] = output
                    else:
                        had_failures = True
            except subprocess.CalledProcessError:
                for future in future_to_job:
                    future.cancel()
                raise

        outputs = [indexed_outputs[index] for index in sorted(indexed_outputs)]
        return outputs, had_failures

    def _record_compile_command(self, cwd: Path, source_path: Path, compiler: str, flags: list[str], output: Path) -> None:
        if self.compile_commands_path is None:
            return
        self.compile_commands.append(
            CompileCommand(
                directory=str(cwd.resolve()),
                file=str(source_path.resolve()),
                arguments=[compiler, *flags, '-c', str(source_path.resolve()), '-o', str(output.resolve())],
                output=str(output.resolve()),
            )
        )

    def _merge_variables(self, raw_variables: dict[str, str]) -> None:
        unresolved = dict(raw_variables)
        while unresolved:
            progress_made = False
            for key in list(unresolved):
                value = unresolved[key]
                try:
                    self.variables[key] = value.format_map(self.variables)
                except KeyError:
                    continue
                del unresolved[key]
                progress_made = True
            if not progress_made:
                unresolved_keys = ', '.join(sorted(unresolved))
                raise BuildSpecError(f'Unable to resolve build variables: {unresolved_keys}')


class UTSBuilder:
    def __init__(self, workspace_root: Path, builddir: str, config_path: str | None, dry_run: bool = False, parallel_enabled: bool = True, compile_commands_path: str | None = None):
        self.workspace_root = workspace_root
        self.builddir = (workspace_root / builddir).resolve()
        self.config_path = self._resolve_config_path(config_path)
        self.dry_run = dry_run
        self.parallel_enabled = parallel_enabled
        self.compile_commands_path = self._resolve_output_path(compile_commands_path)

    def build(self, target: str, list_targets: bool = False) -> None:
        plan = _load_build_plan(self.config_path)
        runner = BuildRunner(
            workspace_root=self.workspace_root,
            builddir=self.builddir,
            toolchain=plan.toolchain,
            variables=plan.variables,
            profiles=plan.profiles,
            source_views=plan.source_views,
            dry_run=self.dry_run,
            parallel_enabled=self.parallel_enabled,
            compile_commands_path=self.compile_commands_path,
        )
        if list_targets:
            for name, raw_target in sorted(plan.targets.items()):
                description = str(raw_target.get('description', '')).strip()
                if description:
                    print(f'{name}: {description}')
                else:
                    print(name)
            return
        try:
            runner.run_target(plan.targets, target)
        finally:
            runner.write_compile_commands()

    def _resolve_config_path(self, config_path: str | None) -> Path:
        if config_path is None:
            return (self.workspace_root / DEFAULT_UTS_CONFIG).resolve()
        candidate = Path(config_path)
        if candidate.is_absolute():
            return candidate
        return (self.workspace_root / candidate).resolve()

    def _resolve_output_path(self, output_path: str | None) -> Path | None:
        if output_path is None:
            return None
        candidate = Path(output_path)
        if candidate.is_absolute():
            return candidate
        return (self.workspace_root / candidate).resolve()


def _load_build_plan(config_path: Path) -> BuildPlan:
    if yaml is None:
        raise BuildSpecError('PyYAML is required. Install it with: pip install -r requirements.txt')
    typed_raw = _load_build_spec_mapping(config_path, ())

    raw_targets = typed_raw.get('targets')
    if not isinstance(raw_targets, dict) or not raw_targets:
        raise BuildSpecError(f'Build config must define a non-empty targets mapping: {config_path}')
    typed_targets = cast(dict[Any, Any], raw_targets)

    raw_variables = typed_raw.get('variables', {})
    if not isinstance(raw_variables, dict):
        raise BuildSpecError('variables must be a mapping of string keys to string values')
    typed_variables = cast(dict[Any, Any], raw_variables)

    raw_profiles = typed_raw.get('profiles', {})
    if not isinstance(raw_profiles, dict):
        raise BuildSpecError('profiles must be a mapping of names to mappings')
    typed_profiles = cast(dict[Any, Any], raw_profiles)

    raw_source_views = typed_raw.get('source_views', {})
    if not isinstance(raw_source_views, dict):
        raise BuildSpecError('source_views must be a mapping of names to mappings')
    typed_source_views = cast(dict[Any, Any], raw_source_views)

    return BuildPlan(
        toolchain=Toolchain.from_dict(_mapping(typed_raw.get('toolchain', {}), 'toolchain')),
        variables={str(key): str(value) for key, value in typed_variables.items()},
        profiles={str(name): _mapping(profile, f'profiles.{name}') for name, profile in typed_profiles.items()},
        source_views={str(name): _mapping(view, f'source_views.{name}') for name, view in typed_source_views.items()},
        targets={str(name): _mapping(target, f'targets.{name}') for name, target in typed_targets.items()},
    )


def _load_build_spec_mapping(config_path: Path, ancestry: tuple[Path, ...]) -> dict[str, Any]:
    resolved_config_path = config_path.resolve()
    if resolved_config_path in ancestry:
        cycle = ' -> '.join(str(path) for path in (*ancestry, resolved_config_path))
        raise BuildSpecError(f'Build config include cycle detected: {cycle}')
    if not resolved_config_path.exists():
        raise BuildSpecError(f'Build config not found: {resolved_config_path}')

    raw = yaml.safe_load(resolved_config_path.read_text(encoding='utf-8'))
    if raw is None:
        typed_raw: dict[Any, Any] = {}
    elif isinstance(raw, dict):
        typed_raw = cast(dict[Any, Any], raw)
    else:
        raise BuildSpecError(f'Build config must be a mapping: {resolved_config_path}')

    merged: dict[str, Any] = {section: {} for section in MERGEABLE_BUILD_SPEC_SECTIONS}
    includes = _string_list(typed_raw.get('includes', []), f'includes in {resolved_config_path}')
    for include in includes:
        include_path = Path(include)
        if not include_path.is_absolute():
            include_path = (resolved_config_path.parent / include_path).resolve()
        included_mapping = _load_build_spec_mapping(include_path, (*ancestry, resolved_config_path))
        _merge_build_spec_mapping(merged, included_mapping, include_path)

    _merge_build_spec_mapping(merged, typed_raw, resolved_config_path)
    return merged


def _merge_build_spec_mapping(merged: dict[str, Any], incoming: dict[str, Any], source_path: Path) -> None:
    for section in MERGEABLE_BUILD_SPEC_SECTIONS:
        raw_section = incoming.get(section)
        if raw_section is None:
            continue
        section_mapping = _mapping(raw_section, f'{section} in {source_path}')
        merged_section = cast(dict[str, Any], merged[section])
        for key, value in section_mapping.items():
            string_key = str(key)
            if string_key in merged_section:
                if merged_section[string_key] != value:
                    raise BuildSpecError(f'Duplicate build spec entry for {section}.{string_key} while loading {source_path}')
                continue
            merged_section[string_key] = value


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildSpecError(f'{field_name} must be a mapping')
    return cast(dict[str, Any], value)


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BuildSpecError(f'{field_name} must be a list')
    typed_value = cast(list[Any], value)
    return [str(item) for item in typed_value]


def _step_list(target: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = target.get('steps', [])
    if not isinstance(raw_steps, list):
        raise BuildSpecError('target steps must be a list')
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(cast(list[Any], raw_steps)):
        if not isinstance(step, dict):
            raise BuildSpecError(f'target step at index {index} must be a mapping')
        steps.append(cast(dict[str, Any], step))
    return steps


def _mapping_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise BuildSpecError(f'{field_name} must be a list')
    items: list[dict[str, Any]] = []
    for index, item in enumerate(cast(list[Any], value)):
        if not isinstance(item, dict):
            raise BuildSpecError(f'{field_name}[{index}] must be a mapping')
        items.append(cast(dict[str, Any], item))
    return items


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if value is None:
        raise BuildSpecError(f'Missing required field: {key}')
    return str(value)


def _bool_value(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise BuildSpecError(f'{field_name} must be a boolean')


def _positive_int_value(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BuildSpecError(f'{field_name} must be a positive integer')
    if value < 1:
        raise BuildSpecError(f'{field_name} must be greater than zero')
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='SVR4 builder.')
    parser.add_argument('--subsystem', '-s', type=str, default='uts', help='Subsystem to build (default: uts)')
    parser.add_argument('--target', '-t', type=str, default='kernel-at386', help='Target to build from the selected config')
    parser.add_argument('--config', '-c', type=str, help='YAML build config to load')
    parser.add_argument('--builddir', '-b', type=str, default='build', help='Directory to place build artifacts (default: build)')
    parser.add_argument('--list-targets', action='store_true', help='List targets in the selected build config and exit')
    parser.add_argument('--dry-run', action='store_true', help='Print commands without running them')
    parser.add_argument('--emit-compile-commands', nargs='?', const='compile_commands.json', metavar='PATH', help='Write a compile_commands.json-style database while processing compile steps')
    parser.add_argument('--no-parallel', action='store_true', help='Force all steps to run without parallel workers')
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    script_root = Path(__file__).resolve().parent
    if (script_root / 'i386').exists() and (script_root / 'build-specs').exists():
        workspace_root = script_root.parent
    else:
        workspace_root = script_root

    if args.subsystem != 'uts':
        raise BuildSpecError(f'Unknown subsystem: {args.subsystem}')

    builder = UTSBuilder(
        workspace_root=workspace_root,
        builddir=args.builddir,
        config_path=args.config,
        dry_run=args.dry_run,
        parallel_enabled=not args.no_parallel,
        compile_commands_path=args.emit_compile_commands,
    )
    builder.build(target=args.target, list_targets=args.list_targets)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except BuildSpecError as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
    except subprocess.CalledProcessError as exc:
        print(f'error: command failed with exit code {exc.returncode}: {exc.cmd}', file=sys.stderr)
        raise SystemExit(exc.returncode) from exc