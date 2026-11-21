"""Lift an early default arm shared by case gotos to a continuation after the switch."""

import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_default_tail'
FAMILIES = (FAMILY,)

_SPACE = re.compile(r'\s*')
_SWITCH = re.compile(r'\bswitch\s*\(')
_CASE = re.compile(r'\b(?P<label>default\s*:|case\b)|[{}]')
_JOIN = re.compile(r'\s*(?P<label>[A-Za-z_]\w*)\s*:(?!:)')
_BREAK = re.compile(r'\bbreak\s*;')
_TERMINATOR = re.compile(r'\bbreak\s*;\s*$')
_CONTROL = re.compile(r'\b(?:switch|for|while)\s*\(|\bdo\s*(?=\{)')


def _body(text, condition):
    start = close(text, condition) if text[condition] == '(' else condition
    if start is None:
        return None
    opening = _SPACE.match(text, start).end()
    if text[opening:opening + 1] != '{':
        return None
    end = close(text, opening, '{', '}')
    return (opening, end) if end is not None else None


def _has_outer_break(text):
    nested = []
    for control in _CONTROL.finditer(text):
        start = control.end() - 1 if control[0].endswith('(') else control.end()
        body = _body(text, start)
        if body:
            nested.append(body)
    return any(not any(start < hit.start() < end for start, end in nested)
               for hit in _BREAK.finditer(text))


def _default_bounds(text, opening, end):
    depth = 0
    default = None
    for token in _CASE.finditer(text, opening + 1, end - 1):
        if token[0] == '{':
            depth += 1
        elif token[0] == '}':
            depth -= 1
        elif depth == 0:
            if default:
                return default, token.start()
            if token[0].startswith('default'):
                default = token
    return None


def variants(source, name):
    """Leave a jump at the old entry and let existing breaks skip the lifted tail."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    for switch in _SWITCH.finditer(clean, *span):
        before = clean[:switch.start()].rstrip()
        if not before or before[-1] not in '{;}':
            continue
        body = _body(clean, switch.end() - 1)
        if not body:
            continue
        opening, end = body
        if re.search(r'(?m)^\s*#', clean[opening:end]):
            continue
        bounds = _default_bounds(clean, opening, end)
        if not bounds:
            continue
        default, next_case = bounds
        join = _JOIN.match(clean, default.end(), next_case)
        terminator = _TERMINATOR.search(clean, default.end(), next_case)
        if not join or not terminator or join.end() >= terminator.start():
            continue
        target = join['label']
        if not re.search(rf'\bgoto\s+{re.escape(target)}\s*;', clean[next_case:end]):
            continue
        tail = clean[join.end():terminator.start()]
        if not tail.rstrip().endswith((';', '}')) or _has_outer_break(tail):
            continue

        # In the old code a break from another case bypasses the default body.
        # Keep that path even when GCC can prove the extra jump dead.
        skip = 'after_switch_tail'
        while re.search(rf'\b{skip}\b', clean):
            skip += '_'
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, switch.start()) + 1:])[0]
        label_start = join.start('label')
        lifted = source[label_start:terminator.start()].rstrip()
        case_line = source.rfind('\n', default.end(), next_case) + 1
        suffix = source[case_line:end] if not clean[case_line:next_case].strip() else source[next_case:end]
        replacement = (
            f' goto {target};\n{suffix}\n'
            f'{indent}goto {skip};\n{indent}{lifted}\n{indent}{skip}: ;'
        )
        return [(FAMILY, source[:default.end()] + replacement + source[end:])]
    return []
