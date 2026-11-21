"""Recover candidate-owned external names from unambiguous MIPS relocations."""
import re

from .csource import _blank, _code_only

NAME = r'[A-Za-z_]\w*'
DATA = re.compile(rf'%((?:hi|lo))\((\??)({NAME})(\+0x[0-9a-f]+)?\)')
CALL = re.compile(rf'jal\s+(\??)({NAME})$')


def reference(instruction):
    if match := DATA.search(instruction):
        kind, missing, name, offset = match.groups()
        start, end = match.span(3)
        return kind, bool(missing), name, offset, instruction[:start].removesuffix('?') + instruction[end:]
    if match := CALL.fullmatch(instruction):
        return 'call', bool(match[1]), match[2], None, 'jal '
    return None


def replacement(source, rows, unresolved, header=''):
    """Propose a source-only rewrite when every missing reference agrees with the target."""
    names = set(unresolved)
    evidence = {name: set() for name in names}
    kinds = {name: set() for name in names}
    for marker, target, candidate in rows:
        ref = reference(candidate)
        if not ref or not ref[1] or ref[2] not in names:
            continue
        kind, _, name, offset, shape = ref
        other = reference(target)
        if marker != 'i' or not other or other[1] or (other[0], other[3], other[4]) != (kind, offset, shape):
            return None
        evidence[name].add(other[2])
        kinds[name].add(kind)
    if not names or any(len(evidence[name]) != 1 or kinds[name] not in ({'hi', 'lo'}, {'call'}) for name in names):
        return None

    aliases = {name: next(iter(evidence[name])) for name in names}
    targets = set(aliases.values())
    if len(targets) != len(names) or names & targets:
        return None
    tokens = re.compile(rf'\b(?:{"|".join(map(re.escape, sorted(names)))})\b')
    if tokens.search(_blank(header)):
        return None
    matches = list(tokens.finditer(_code_only(source)))
    if {match[0] for match in matches} != names:
        return None
    for match in reversed(matches):
        start, end = match.span()
        source = source[:start] + aliases[match[0]] + source[end:]
    return source
