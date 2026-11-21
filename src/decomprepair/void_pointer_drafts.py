"""Spell m2c's literal byte offsets on void pointers in portable C."""

import re

from .csource import _blank, find

_NAME = r'[A-Za-z_]\w*'
_VOID_POINTER = r'(?P<type>(?:const\s+|volatile\s+)*void)\s*\*\s*(?P<name>' + _NAME + r')'
_PARAM = re.compile(r'(?:\(|,)\s*' + _VOID_POINTER + r'\s*(?=[,)])')
_LOCAL = re.compile(r'^[ \t]*' + _VOID_POINTER + r'\s*;', re.M)
_OFFSET = r'(?:0[xX][\da-fA-F]+|\d+)[uUlL]*'
_ASSIGNMENT = re.compile(
    r'^[ \t]*(?:\*\s*)?' + _NAME + r'\s*=\s*(?P<base>' + _NAME + r')'
    r'\s*[+-]\s*' + _OFFSET + r'\s*;', re.M
)

_STEP = re.compile(
    r'^[ \t]*(?P<base>' + _NAME + r')\s*(?P<op>[+-])=\s*(?=' + _OFFSET + r'\s*;)', re.M
)


def rewrite(source: str, name: str) -> str | None:
    """Cast simple assignment bases with explicit m2c parameter or local types."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    opening = clean.index('{', start, end)
    body = clean[opening + 1:end]
    pointers = {
        match['name']: match['type'] for match in _PARAM.finditer(clean[start:opening])
    }
    # m2c declares its temporaries together at the start of the function.
    for match in _LOCAL.finditer(body):
        if '{' not in body[:match.start()]:
            pointers[match['name']] = match['type']

    byte_types = {
        local: ctype.removesuffix('void') + 'unsigned char' for local, ctype in pointers.items()
    }
    edits = []
    for match in _ASSIGNMENT.finditer(body):
        if ctype := byte_types.get(match['base']):
            # Keep qualifiers and apply the cast to the base so the literal stays a byte count.
            at = match.start('base')
            edits.append((at, at, f'({ctype} *) '))
    for match in _STEP.finditer(body):
        if ctype := byte_types.get(match['base']):
            base = match['base']
            edits.append((match.start('base'), match.end(), f"{base} = ({ctype} *) {base} {match['op']} "))
    if not edits:
        return None
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:opening + 1 + start] + replacement + source[opening + 1 + end:]
    return source
