#!/usr/bin/env python3

from __future__ import annotations

import argparse
import dataclasses
import difflib
import re
import sys
from pathlib import Path


KNR_HEADER = re.compile(
    r'^(?P<indent>[ \t]*)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<params>[^;{}]*)\)\s*$'
)
REGISTER_IMPLICIT_INT = re.compile(
    r'^(?P<indent>[ \t]*)register\s+(?P<names>[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)\s*;\s*$'
)
NON_PROTOTYPE_DECLARATION = re.compile(
    r'^(?P<indent>[ \t]*)(?P<prefix>(?:(?:extern|STATIC|static)\s+)?)'
    r'(?P<return_spec>[A-Za-z_][A-Za-z0-9_ \t]*(?:\s*\*+)?)\s*'
    r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)\(\)\s*;\s*$'
)
GROUPED_NON_PROTOTYPE_DECLARATION = re.compile(
    r'^(?P<indent>[ \t]*)(?P<prefix>(?:(?:extern|STATIC|static)\s+)?)'
    r'(?P<return_spec>[A-Za-z_][A-Za-z0-9_ \t]*(?:\s*\*+)?)\s*'
    r'(?P<declarators>[A-Za-z_][A-Za-z0-9_]*\(\)(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*\(\))+)\s*;\s*$'
)
IDENTIFIER = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')
PP_DIRECTIVE = re.compile(r'^#\s*(?P<directive>if|ifdef|ifndef|else|elif|endif)\b')

TYPE_KEYWORDS = {
    'char',
    'double',
    'enum',
    'float',
    'int',
    'long',
    'short',
    'signed',
    'struct',
    'union',
    'unsigned',
    'void',
}

STORAGE_ONLY = {
    'extern',
    'register',
    'static',
}

CONTROL_KEYWORDS = {
    'for',
    'if',
    'switch',
    'while',
}


@dataclasses.dataclass
class RewriteStats:
    converted_functions: int = 0
    fixed_register_ints: int = 0
    prototyped_declarations: int = 0
    skipped_functions: int = 0
    skipped_details: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class FunctionCandidate:
    header_index: int
    body_index: int
    indent: str
    name: str
    params: list[str]
    param_declarations: dict[str, str]


@dataclasses.dataclass(frozen=True)
class FunctionSignature:
    return_specifier: str
    params: list[str]
    param_declarations: dict[str, str]


@dataclasses.dataclass(frozen=True)
class StdcWrappedFunctionCandidate:
    wrapper_index: int
    body_index: int
    name: str
    ansi_header: str
    params: list[str]
    param_declarations: dict[str, str]


@dataclasses.dataclass(frozen=True)
class ConditionalFunctionCandidate:
    wrapper_index: int
    body_index: int
    name: str
    signature_block: str


def is_typeish_line(text: str) -> bool:
    if not text:
        return False
    if any(char in text for char in ';{}()[]:=#,'):
        return False
    return bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_ \t*]*', text))


def has_explicit_type(return_spec: str) -> bool:
    words = IDENTIFIER.findall(return_spec)
    return any(word in TYPE_KEYWORDS or word.endswith('_t') for word in words)


def normalize_return_specifier(return_lines: list[str]) -> str:
    if not return_lines:
        return 'int'

    merged = ' '.join(line.strip() for line in return_lines)
    normalized = ' '.join(merged.split())
    if not normalized:
        return 'int'
    if has_explicit_type(normalized):
        return normalized

    words = IDENTIFIER.findall(normalized)
    if words and all(word in STORAGE_ONLY for word in words):
        return f'{normalized} int'
    return normalized


def normalized_preprocessor_line(text: str) -> str:
    stripped, _ = strip_declaration_comments(text, False)
    return stripped.strip()


def preprocessor_directive_kind(text: str) -> str | None:
    match = PP_DIRECTIVE.match(normalized_preprocessor_line(text))
    if match is None:
        return None
    return match.group('directive')


def collect_trailing_typeish_lines(lines: list[str]) -> list[str]:
    trailing: list[str] = []
    for line in lines:
        stripped = line.strip()
        if is_typeish_line(stripped):
            trailing.append(line)
        else:
            trailing = []
    return trailing


def external_return_specifier(lines: list[str], start: int) -> str | None:
    trailing = collect_trailing_typeish_lines(lines[max(0, start - 2):start])
    if not trailing:
        return None
    return normalize_return_specifier(trailing)


def is_stdc_condition_line(condition_line: str) -> bool:
    return condition_line in {'#ifdef __STDC__', '#if __STDC__'}


def is_asm_return_specifier(return_specifier: str) -> bool:
    return 'asm' in IDENTIFIER.findall(return_specifier)


def promoted_type_specifier(type_specifier: str) -> str:
    normalized = ' '.join(type_specifier.split())
    if not normalized:
        return 'int'
    if normalized.startswith('enum '):
        return 'int'
    if normalized in {
        'char',
        'signed char',
        'unsigned char',
        'short',
        'short int',
        'signed short',
        'signed short int',
        'unsigned short',
        'unsigned short int',
        'float',
    }:
        return 'double' if normalized == 'float' else 'int'
    return normalized


def normalize_parameter_fragment(fragment: str, promote_default: bool = True) -> str:
    identifiers = IDENTIFIER.findall(fragment)
    if not identifiers:
        return fragment.strip()

    param_name = identifiers[-1]
    matches = list(re.finditer(rf'\b{re.escape(param_name)}\b', fragment))
    if not matches:
        return fragment.strip()

    match = matches[-1]
    before = fragment[:match.start()].rstrip()
    after = fragment[match.end():].rstrip()
    if '(' in before or '(' in after or '[' in after:
        return fragment.strip()

    pointer_match = re.search(r'(\s*\*+)\s*$', before)
    if pointer_match is None:
        pointer_part = ''
        base_part = before
    else:
        pointer_part = pointer_match.group(1).strip()
        base_part = before[:pointer_match.start()].rstrip()

    tokens = base_part.split()
    storage_tokens: list[str] = []
    while tokens and tokens[0] in STORAGE_ONLY:
        storage_tokens.append(tokens.pop(0))

    type_specifier = ' '.join(tokens)
    if promote_default and not pointer_part:
        type_specifier = promoted_type_specifier(type_specifier)
    elif not type_specifier:
        type_specifier = 'int'

    left_parts = [*storage_tokens]
    if type_specifier:
        left_parts.append(type_specifier)
    left = ' '.join(left_parts).strip()

    if pointer_part:
        left = f'{left} {pointer_part}'.strip()
    if after:
        return f'{left} {param_name}{after}'.strip()
    return f'{left} {param_name}'.strip()


def is_simple_typeish_prefix(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    normalized = ' '.join(stripped.replace('*', ' ').split())
    if not normalized:
        return False
    if normalized in {'asm'}:
        return True
    return is_typeish_line(normalized)


def parse_same_line_call_argument_count(line: str, start_index: int) -> int | None:
    open_index = line.find('(', start_index)
    if open_index == -1:
        return None

    depth = 1
    arg_count = 0
    saw_token = False
    index = open_index + 1
    quote: str | None = None
    while index < len(line):
        char = line[index]
        if quote is not None:
            if char == '\\':
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue

        if char in {'"', "'"}:
            quote = char
            saw_token = True
            index += 1
            continue
        if char == '(':
            depth += 1
            saw_token = True
            index += 1
            continue
        if char == ')':
            depth -= 1
            if depth == 0:
                if not saw_token and arg_count == 0:
                    return 0
                return arg_count + 1
            index += 1
            continue
        if depth == 1 and char == ',':
            arg_count += 1
            saw_token = False
            index += 1
            continue
        if not char.isspace():
            saw_token = True
        index += 1
    return None


def iter_simple_call_sites(lines: list[str], name: str) -> list[tuple[int, int]]:
    pattern = re.compile(rf'\b{re.escape(name)}\s*\(')
    sites: list[tuple[int, int]] = []
    in_block_comment = False
    for line_index, line in enumerate(lines):
        stripped_line, in_block_comment = strip_declaration_comments(line, in_block_comment)
        if not stripped_line.strip() or stripped_line.lstrip().startswith('#'):
            continue
        for match in pattern.finditer(stripped_line):
            prefix = stripped_line[:match.start()]
            if not prefix.strip() and not stripped_line[:match.start()].startswith((' ', '\t')):
                continue
            if is_simple_typeish_prefix(prefix):
                continue
            arg_count = parse_same_line_call_argument_count(stripped_line, match.start())
            if arg_count is None:
                continue
            sites.append((line_index, arg_count))
    return sites


def has_call_arity_mismatch(
    lines: list[str], name: str, param_count: int, header_index: int, body_index: int
) -> bool:
    for line_index, arg_count in iter_simple_call_sites(lines, name):
        if header_index <= line_index <= body_index:
            continue
        if arg_count != param_count:
            return True
    return False


def has_predefinition_call(lines: list[str], name: str, header_index: int) -> bool:
    return any(line_index < header_index for line_index, _ in iter_simple_call_sites(lines, name))


def header_region_lead_kind(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return 'blank'
    if preprocessor_directive_kind(line) is not None:
        return 'directive'
    if is_typeish_line(stripped):
        return 'type'
    if KNR_HEADER.match(line) is not None:
        return 'header'
    return 'other'


def parse_param_list(raw_params: str) -> list[str] | None:
    stripped = raw_params.strip()
    if not stripped:
        return []
    if stripped == 'void':
        return None

    names = [part.strip() for part in stripped.split(',')]
    if not names:
        return []
    if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in names):
        return None
    return names


def declaration_hits(body: str, params: list[str]) -> list[str]:
    hits: list[str] = []
    for param in params:
        if re.search(rf'\b{re.escape(param)}\b', body):
            hits.append(param)
    return hits


def declared_param_name(fragment: str, params: list[str]) -> str | None:
    identifiers = [identifier for identifier in IDENTIFIER.findall(fragment) if identifier in params]
    if not identifiers:
        return None
    return identifiers[-1]


def is_nonfunction_name(name: str) -> bool:
    return name in CONTROL_KEYWORDS or name.upper() == name


def looks_like_old_style_context(lines: list[str], start: int, params: list[str]) -> bool:
    index = start + 1
    in_block_comment = False
    while index < len(lines):
        stripped, in_block_comment = strip_declaration_comments(lines[index], in_block_comment)
        stripped = stripped.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith('{') or stripped.startswith('#'):
            return True
        if stripped.endswith(';'):
            return bool(params) and bool(declaration_hits(stripped[:-1], params))
        return False
    return False


def has_meaningful_declaration_lines(lines: list[str]) -> bool:
    in_block_comment = False
    for line in lines:
        stripped, in_block_comment = strip_declaration_comments(line, in_block_comment)
        stripped = stripped.strip()
        if stripped and not stripped.startswith('#'):
            return True
    return False


def strip_declaration_comments(text: str, in_block_comment: bool) -> tuple[str, bool]:
    cleaned: list[str] = []
    index = 0
    while index < len(text):
        if in_block_comment:
            end = text.find('*/', index)
            if end == -1:
                return ''.join(cleaned), True
            in_block_comment = False
            index = end + 2
            continue

        block = text.find('/*', index)
        line_comment = text.find('//', index)
        if line_comment != -1 and (block == -1 or line_comment < block):
            cleaned.append(text[index:line_comment])
            break

        if block == -1:
            cleaned.append(text[index:])
            break

        cleaned.append(text[index:block])
        index = block + 2
        in_block_comment = True

    return ''.join(cleaned), in_block_comment


def split_parameter_declaration_fragments(body: str, params: list[str]) -> list[str] | None:
    parts = [part.strip() for part in body.split(',')]
    if len(parts) <= 1:
        return [body]

    first_name = declared_param_name(parts[0], params)
    if first_name is None:
        return None

    first_matches = list(re.finditer(rf'\b{re.escape(first_name)}\b', parts[0]))
    if not first_matches:
        return None
    first_match = first_matches[-1]

    prefix = parts[0][:first_match.start()].rstrip()
    if not prefix:
        return None

    if ' ' in prefix:
        head, tail = prefix.rsplit(None, 1)
        if tail and set(tail) <= {'*'}:
            shared_base = head
        else:
            shared_base = prefix
    else:
        shared_base = prefix

    if not shared_base:
        return None

    fragments = [parts[0]]
    for part in parts[1:]:
        if not part:
            return None
        fragments.append(f'{shared_base} {part}')
    return fragments


def parse_param_declarations(lines: list[str], params: list[str]) -> dict[str, str] | None:
    mapping: dict[str, str] = {}
    in_block_comment = False
    pending = ''
    for line in lines:
        stripped, in_block_comment = strip_declaration_comments(line, in_block_comment)
        stripped = stripped.strip()
        if not stripped or stripped.startswith('#'):
            continue

        pending = f'{pending} {stripped}'.strip() if pending else stripped
        if not pending.endswith(';'):
            continue

        if not pending.endswith(';'):
            return None

        body = pending[:-1].strip()
        pending = ''
        fragments = split_parameter_declaration_fragments(body, params)
        if fragments is None:
            return None

        for fragment in fragments:
            param_name = declared_param_name(fragment, params)
            if param_name is None:
                return None
            if param_name in mapping:
                return None
            mapping[param_name] = fragment

    if pending:
        return None

    for param in params:
        if param not in mapping:
            mapping[param] = f'int {param}'

    return mapping


def scan_old_style_function(lines: list[str], start: int) -> FunctionCandidate | None:
    match = KNR_HEADER.match(lines[start])
    if match is None:
        return None
    if is_nonfunction_name(match.group('name')):
        return None

    params = parse_param_list(match.group('params'))
    if params is None:
        return None

    index = start + 1
    declaration_lines: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith('{'):
            break
        if not stripped:
            index += 1
            continue
        declaration_lines.append(lines[index])
        index += 1

    if index >= len(lines) or not lines[index].strip().startswith('{'):
        return None

    if not params:
        if has_meaningful_declaration_lines(declaration_lines):
            return None
        return FunctionCandidate(
            header_index=start,
            body_index=index,
            indent=match.group('indent'),
            name=match.group('name'),
            params=[],
            param_declarations={},
        )

    param_declarations = parse_param_declarations(declaration_lines, params)
    if param_declarations is None:
        return None

    return FunctionCandidate(
        header_index=start,
        body_index=index,
        indent=match.group('indent'),
        name=match.group('name'),
        params=params,
        param_declarations=param_declarations,
    )


def scan_stdc_wrapped_function(lines: list[str], start: int) -> StdcWrappedFunctionCandidate | None:
    if lines[start].strip() != '#ifdef __STDC__':
        return None

    index = start + 1
    ansi_lines: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == '#else':
            break
        if stripped:
            ansi_lines.append(stripped)
        index += 1

    if index >= len(lines) or lines[index].strip() != '#else' or not ansi_lines:
        return None

    old_style_index = index + 1
    while old_style_index < len(lines) and not lines[old_style_index].strip():
        old_style_index += 1

    candidate = scan_old_style_function(lines, old_style_index)
    if candidate is None:
        return None
    if not any(lines[i].strip() == '#endif' for i in range(old_style_index, candidate.body_index)):
        return None

    ansi_header = ' '.join(ansi_lines).strip()
    match = re.fullmatch(r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<params>.*)\)', ansi_header)
    if match is None or match.group('name') != candidate.name:
        return None

    return StdcWrappedFunctionCandidate(
        wrapper_index=start,
        body_index=candidate.body_index,
        name=candidate.name,
        ansi_header=ansi_header,
        params=candidate.params,
        param_declarations=candidate.param_declarations,
    )


def candidate_return_specifier(lines: list[str], start: int) -> str:
    return normalize_return_specifier(collect_trailing_typeish_lines(lines[max(0, start - 2):start]))


def has_prior_declaration(lines: list[str], name: str, header_index: int) -> bool:
    declaration_pattern = re.compile(rf'\b{re.escape(name)}\s*\([^;{{}}]*\)\s*;')
    for line in lines[:header_index]:
        match = declaration_pattern.search(line)
        if match is None:
            continue
        prefix = line[:match.start()]
        if not prefix.strip() and not line.startswith((' ', '\t')):
            return True
        if is_simple_typeish_prefix(prefix):
            return True
    return False


def should_rewrite_candidate(lines: list[str], candidate: FunctionCandidate) -> bool:
    return_specifier = candidate_return_specifier(lines, candidate.header_index)
    if is_asm_return_specifier(return_specifier):
        return False
    if has_call_arity_mismatch(
        lines,
        candidate.name,
        len(candidate.params),
        candidate.header_index,
        candidate.body_index,
    ):
        return False
    if has_predefinition_call(lines, candidate.name, candidate.header_index) and not has_prior_declaration(
        lines, candidate.name, candidate.header_index
    ):
        return False
    return True


def build_signature_from_lines(
    block_lines: list[str], default_return_specifier: str | None = None
) -> tuple[str, str] | None:
    candidate_lines = [line for line in block_lines if line.strip()]
    if not candidate_lines:
        return None

    temp_lines = [*candidate_lines, '{\n']
    for index in range(len(candidate_lines)):
        lead_kind = header_region_lead_kind(candidate_lines[index])
        if lead_kind in {'blank', 'directive', 'type'}:
            continue
        if lead_kind != 'header':
            return None

        candidate = scan_old_style_function(temp_lines, index)
        if candidate is None:
            return None

        return_lines = temp_lines[max(0, index - 2):index]
        trailing: list[str] = []
        for line in return_lines:
            stripped = line.strip()
            if is_typeish_line(stripped):
                trailing.append(line)
            else:
                trailing = []
        if trailing:
            return_specifier = normalize_return_specifier(trailing)
        elif default_return_specifier is not None:
            return_specifier = default_return_specifier
        else:
            return_specifier = normalize_return_specifier(trailing)
        if is_asm_return_specifier(return_specifier):
            return None
        return candidate.name, build_signature(candidate, return_specifier)
    return None


def find_top_level_conditional_bounds(lines: list[str], start: int = 0) -> tuple[int | None, int] | None:
    if start >= len(lines):
        return None
    if preprocessor_directive_kind(lines[start]) not in {'if', 'ifdef', 'ifndef'}:
        return None

    depth = 0
    else_index: int | None = None
    index = start
    while index < len(lines):
        directive = preprocessor_directive_kind(lines[index])
        if directive in {'if', 'ifdef', 'ifndef'}:
            depth += 1
        elif directive == 'else' and depth == 1 and else_index is None:
            else_index = index
        elif directive == 'endif':
            depth -= 1
            if depth == 0:
                return else_index, index
            if depth < 0:
                return None
        index += 1
    return None


def split_conditional_tail_lines(
    condition_line: str, lines: list[str]
) -> tuple[list[str], list[str], list[str]] | None:
    shared: list[str] = []
    true_lines: list[str] = []
    false_lines: list[str] = []
    index = 0
    while index < len(lines):
        stripped = normalized_preprocessor_line(lines[index])
        directive = preprocessor_directive_kind(lines[index])
        if stripped == condition_line:
            index += 1
            branch_true: list[str] = []
            branch_false: list[str] = []
            saw_else = False
            while index < len(lines):
                directive = preprocessor_directive_kind(lines[index])
                if directive == 'else':
                    saw_else = True
                    index += 1
                    break
                if directive == 'endif':
                    true_lines.extend(branch_true)
                    false_lines.extend(branch_false)
                    index += 1
                    break
                branch_true.append(lines[index])
                index += 1
            else:
                return None

            if not saw_else:
                continue

            while index < len(lines):
                directive = preprocessor_directive_kind(lines[index])
                if directive == 'endif':
                    true_lines.extend(branch_true)
                    false_lines.extend(branch_false)
                    index += 1
                    break
                branch_false.append(lines[index])
                index += 1
            else:
                return None
            continue

        if directive is not None:
            return None

        shared.append(lines[index])
        index += 1

    return shared, true_lines, false_lines


def rewrite_function_header_region(
    lines: list[str], default_return_specifier: str | None = None
) -> tuple[str, str] | None:
    direct = build_signature_from_lines(lines, default_return_specifier)
    if direct is not None:
        return direct

    if not lines:
        return None

    condition_line = normalized_preprocessor_line(lines[0])
    if preprocessor_directive_kind(lines[0]) not in {'if', 'ifdef', 'ifndef'} or is_stdc_condition_line(condition_line):
        return None

    bounds = find_top_level_conditional_bounds(lines)
    if bounds is None:
        return None
    else_index, endif_index = bounds
    if else_index is None:
        return None

    tail_split = split_conditional_tail_lines(condition_line, lines[endif_index + 1:])
    if tail_split is None:
        return None
    shared_lines, true_tail_lines, false_tail_lines = tail_split

    true_result = rewrite_function_header_region(
        lines[1:else_index] + shared_lines + true_tail_lines,
        default_return_specifier,
    )
    false_result = rewrite_function_header_region(
        lines[else_index + 1:endif_index] + shared_lines + false_tail_lines,
        default_return_specifier,
    )
    if true_result is None or false_result is None:
        return None

    true_name, true_signature = true_result
    false_name, false_signature = false_result
    if true_name != false_name:
        return None

    rendered = f'{lines[0]}{true_signature}#else\n{false_signature}#endif\n'
    return true_name, rendered


def scan_conditional_function_wrapper(lines: list[str], start: int) -> ConditionalFunctionCandidate | None:
    condition_line = normalized_preprocessor_line(lines[start])
    if preprocessor_directive_kind(lines[start]) not in {'if', 'ifdef', 'ifndef'} or is_stdc_condition_line(condition_line):
        return None

    bounds = find_top_level_conditional_bounds(lines, start)
    if bounds is None:
        return None
    else_index, endif_index = bounds
    if else_index is None:
        return None

    body_index = endif_index + 1
    while body_index < len(lines) and not lines[body_index].strip().startswith('{'):
        body_index += 1
    if body_index >= len(lines) or not lines[body_index].strip().startswith('{'):
        return None

    rewritten = rewrite_function_header_region(lines[start:body_index], external_return_specifier(lines, start))
    if rewritten is None:
        return None
    name, signature_block = rewritten

    return ConditionalFunctionCandidate(
        wrapper_index=start,
        body_index=body_index,
        name=name,
        signature_block=signature_block,
    )


def pop_return_specifier_lines(output_lines: list[str]) -> list[str]:
    consumed: list[str] = []
    while output_lines and len(consumed) < 2:
        stripped = output_lines[-1].strip()
        if not is_typeish_line(stripped):
            break
        consumed.insert(0, output_lines.pop())
    return consumed


def build_signature(candidate: FunctionCandidate, return_specifier: str) -> str:
    if candidate.params:
        params = ', '.join(
            normalize_parameter_fragment(candidate.param_declarations[name]) for name in candidate.params
        )
    else:
        params = 'void'
    return f'{return_specifier}\n{candidate.name}({params})\n'


def build_wrapped_signature(candidate: StdcWrappedFunctionCandidate, return_specifier: str) -> str:
    return f'{return_specifier}\n{candidate.ansi_header}\n'


def build_conditional_signature(candidate: ConditionalFunctionCandidate) -> str:
    return candidate.signature_block


def build_signature_text(signature: FunctionSignature) -> str:
    if signature.params:
        return ', '.join(
            normalize_parameter_fragment(signature.param_declarations[name]) for name in signature.params
        )
    return 'void'


def build_declaration(
    signature: FunctionSignature,
    indent: str,
    prefix: str,
    return_specifier: str,
    name: str,
) -> str:
    return f'{indent}{prefix}{return_specifier} {name}({build_signature_text(signature)});\n'


def parse_grouped_declarators(raw_declarators: str) -> list[str] | None:
    names: list[str] = []
    for declarator in raw_declarators.split(','):
        stripped = declarator.strip()
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\(\)', stripped)
        if match is None:
            return None
        names.append(match.group(1))
    return names


def collect_function_signatures(lines: list[str]) -> dict[str, FunctionSignature]:
    signatures: dict[str, FunctionSignature] = {}
    index = 0
    while index < len(lines):
        conditional = scan_conditional_function_wrapper(lines, index)
        if conditional is not None:
            index = conditional.body_index + 1
            continue

        wrapped = scan_stdc_wrapped_function(lines, index)
        if wrapped is not None:
            return_lines = lines[max(0, index - 2):index]
            trailing: list[str] = []
            for line in return_lines:
                stripped = line.strip()
                if is_typeish_line(stripped):
                    trailing.append(line)
                else:
                    trailing = []
            signatures[wrapped.name] = FunctionSignature(
                return_specifier=normalize_return_specifier(trailing),
                params=wrapped.params,
                param_declarations=wrapped.param_declarations,
            )
            index = wrapped.body_index + 1
            continue

        candidate = scan_old_style_function(lines, index)
        if candidate is None:
            index += 1
            continue
        if not should_rewrite_candidate(lines, candidate):
            index = candidate.body_index + 1
            continue

        return_lines = lines[max(0, index - 2):index]
        trailing: list[str] = []
        for line in return_lines:
            stripped = line.strip()
            if is_typeish_line(stripped):
                trailing.append(line)
            else:
                trailing = []
        return_specifier = normalize_return_specifier(trailing)
        signatures[candidate.name] = FunctionSignature(
            return_specifier=return_specifier,
            params=candidate.params,
            param_declarations=candidate.param_declarations,
        )
        index = candidate.body_index + 1
    return signatures


def rewrite_same_file_declaration(line: str, signatures: dict[str, FunctionSignature]) -> tuple[str, bool]:
    match = NON_PROTOTYPE_DECLARATION.match(line)
    if match is None:
        group_match = GROUPED_NON_PROTOTYPE_DECLARATION.match(line)
        if group_match is None:
            return line, False

        names = parse_grouped_declarators(group_match.group('declarators'))
        if not names:
            return line, False

        resolved: list[tuple[str, FunctionSignature]] = []
        for name in names:
            signature = signatures.get(name)
            if signature is None:
                return line, False
            resolved.append((name, signature))

        rewritten = ''.join(
            build_declaration(
                signature,
                group_match.group('indent'),
                group_match.group('prefix'),
                group_match.group('return_spec').strip(),
                name,
            )
            for name, signature in resolved
        )
        return rewritten, rewritten != line

    signature = signatures.get(match.group('name'))
    if signature is None:
        return line, False

    rewritten = build_declaration(
        signature,
        match.group('indent'),
        match.group('prefix'),
        match.group('return_spec').strip(),
        match.group('name'),
    )
    return rewritten, rewritten != line


def rewrite_register_implicit_int(line: str) -> tuple[str, bool]:
    match = REGISTER_IMPLICIT_INT.match(line)
    if match is None:
        return line, False
    return f"{match.group('indent')}register int {match.group('names')};\n", True


def rewrite_source(source_text: str, source_name: str) -> tuple[str, RewriteStats]:
    lines = source_text.splitlines(keepends=True)
    signatures = collect_function_signatures(lines)
    rewritten: list[str] = []
    stats = RewriteStats()

    index = 0
    while index < len(lines):
        conditional = scan_conditional_function_wrapper(lines, index)
        if conditional is not None:
            pop_return_specifier_lines(rewritten)
            rewritten.append(build_conditional_signature(conditional))
            rewritten.append(lines[conditional.body_index])
            stats.converted_functions += 1
            index = conditional.body_index + 1
            continue

        wrapped = scan_stdc_wrapped_function(lines, index)
        if wrapped is not None:
            return_lines = pop_return_specifier_lines(rewritten)
            return_specifier = normalize_return_specifier(return_lines)
            rewritten.append(build_wrapped_signature(wrapped, return_specifier))
            rewritten.append(lines[wrapped.body_index])
            stats.converted_functions += 1
            index = wrapped.body_index + 1
            continue

        candidate = scan_old_style_function(lines, index)
        if candidate is not None:
            if not should_rewrite_candidate(lines, candidate):
                rewritten.append(lines[index])
                index += 1
                continue
            return_lines = pop_return_specifier_lines(rewritten)
            return_specifier = normalize_return_specifier(return_lines)
            rewritten.append(build_signature(candidate, return_specifier))
            rewritten.append(lines[candidate.body_index])
            stats.converted_functions += 1
            index = candidate.body_index + 1
            continue

        updated_line, changed = rewrite_register_implicit_int(lines[index])
        if not changed:
            updated_line, changed = rewrite_same_file_declaration(updated_line, signatures)
        rewritten.append(updated_line)
        if changed:
            if REGISTER_IMPLICIT_INT.match(lines[index]) is not None:
                stats.fixed_register_ints += 1
            else:
                stats.prototyped_declarations += 1

        header_match = KNR_HEADER.match(lines[index])
        if header_match is not None:
            if is_nonfunction_name(header_match.group('name')):
                index += 1
                continue
            params = parse_param_list(header_match.group('params'))
            if params is not None and looks_like_old_style_context(lines, index, params):
                stats.skipped_functions += 1
                stats.skipped_details.append(
                    f'{source_name}:{index + 1}: unsupported old-style definition shape for {header_match.group("name")}'
                )
        index += 1

    return ''.join(rewritten), stats


def emit_diff(original: str, rewritten: str, path: Path) -> str:
    return ''.join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            rewritten.splitlines(keepends=True),
            fromfile=str(path),
            tofile=f'{path} (rewritten)',
        )
    )


def print_stats(stats: RewriteStats, quiet: bool) -> None:
    if quiet:
        return

    print(
        (
            f'converted {stats.converted_functions} function definitions, '
            f'fixed {stats.fixed_register_ints} implicit register declarations, '
            f'prototyped {stats.prototyped_declarations} same-file declarations, '
            f'skipped {stats.skipped_functions} unsupported candidates'
        ),
        file=sys.stderr,
    )
    for detail in stats.skipped_details[:10]:
        print(detail, file=sys.stderr)
    if len(stats.skipped_details) > 10:
        remaining = len(stats.skipped_details) - 10
        print(f'... and {remaining} more skipped candidates', file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Pilot rewriter for selected legacy C constructs in the SVR4 kernel tree.'
    )
    parser.add_argument('source', type=Path, help='Path to the C file to rewrite')
    parser.add_argument('-o', '--output', type=Path, help='Write rewritten output to a separate file')
    parser.add_argument('-i', '--in-place', action='store_true', help='Rewrite the input file in place')
    parser.add_argument('--diff', action='store_true', help='Print a unified diff instead of the rewritten file')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress rewrite statistics')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_text = args.source.read_text(encoding='utf-8', errors='replace')
    rewritten, stats = rewrite_source(source_text, str(args.source))

    if args.in_place and args.output is not None:
        raise SystemExit('error: --in-place and --output cannot be used together')

    if args.diff:
        sys.stdout.write(emit_diff(source_text, rewritten, args.source))
    elif args.in_place:
        args.source.write_text(rewritten, encoding='utf-8')
    elif args.output is not None:
        args.output.write_text(rewritten, encoding='utf-8')
    else:
        sys.stdout.write(rewritten)

    print_stats(stats, args.quiet)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())