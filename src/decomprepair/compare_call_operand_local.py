"""A test whose operand is made from a call's result, with that operand held in a local set before the `if`.

    if (obj->level >= (f() != 0) && ready) { .. }   ->  { u32 flag_operand = f() != 0;
                                                          if (obj->level >= flag_operand && ready) { .. } }
    if (obj->level >= (f() ? 2 : 1)) { .. }         ->  { u32 flag_operand = 2;
                                                          if (f() == 0) { flag_operand = 1; }
                                                          if (obj->level >= flag_operand) { .. } }

Written inside the comparison, the compiler may fold the test into a branch of its own (`blez`, `slti`) or load the
other side before the call. With the operand in a local the call comes first, the other side is loaded after it and the
two are compared by one `sltu`. On a 678-instruction N64 projectile update (SN GCC 2.8.1 `-G0 -mips3 -O2 -mfp64`) the
first form was the whole difference at 405 -> 0 (two sites), and the second 4500 -> 0 (three sites). That this is
gcc's `do_jump`/`do_store_flag` folding a flag operand is a hypothesis (SN's compiler has no source); the measurements
are not. Every site of the function is also offered at once, since copies of one arm cross-jump only when they agree.

Only the `if`'s first operand (or its whole condition) is moved, so nothing that was skipped by `&&` or `||` is now
run. The call then runs before the other side is read. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, view
from .pattern_repairs import close

FAMILY = 'compare_call_operand_local'
ALL = 'compare_call_operand_local_all'
FAMILIES = (FAMILY, ALL)
LIMIT = 24
_IF = re.compile(r'\bif\s*\(')
_RELATION = re.compile(r'(?<![<>\-=!])(<=|>=|<(?![<=])|>(?![>=]))')
_CALL = rf'(?P<call>{IDENT}\s*\(\s*(?:{IDENT}(?:\s*,\s*{IDENT})*)?\s*\))'
_CAST = r'(?:\(\s*(?P<cast>u32|s32|unsigned\s+int|unsigned|int)\s*\)\s*)?'
_FLAG = re.compile(rf'{_CAST}\(\s*{_CALL}\s*(?P<op>!=|==)\s*0\s*\)')
_PICK = re.compile(rf'{_CAST}\(\s*\(?\s*{_CALL}\s*(?:(?P<op>!=|==)\s*0\s*)?\)?\s*\?\s*(?P<a>-?{NUMBER})\s*:'
                   rf'\s*(?P<b>-?{NUMBER})\s*\)')
_NOT_CALLS = ('if', 'while', 'for', 'switch', 'return', 'sizeof')


def _first_operand(clean, start, stop):
    """The end of the condition's first `&&`/`||` operand, looking only outside brackets."""
    depth, at = 0, start
    while at < stop:
        char = clean[at]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0 and clean[at:at + 2] in ('&&', '||'):
            return at
        elif depth == 0 and char == '?':
            return start
        at += 1
    return stop


def _statement_end(clean, at):
    """The end of a braced `if` arm from `at`, with its `else` arms; None for a braceless one."""
    brace = re.compile(r'\s*\{').match(clean, at)
    if not brace:
        return None
    end = close(clean, brace.end() - 1, '{', '}')
    if end is None:
        return None
    other = re.compile(r'\s*else\b').match(clean, end)
    if not other:
        return end
    chain = re.compile(r'\s*if\s*\(').match(clean, other.end())
    if chain:
        shut = close(clean, chain.end() - 1)
        return None if shut is None else _statement_end(clean, shut)
    return _statement_end(clean, other.end())


def _operand(source, clean, start, stop):
    """(start, end, lines before the `if`) of a flag or picked-constant operand beside one comparison."""
    relations = []
    for hit in _RELATION.finditer(clean, start, stop):
        before = clean[start:hit.start()]
        if before.count('(') == before.count(')'):
            relations.append(hit)
    if len(relations) != 1:
        return None
    relation = relations[0]
    for lo, hi in ((relation.end(), stop), (start, relation.start())):
        text = clean[lo:hi]
        lo, hi = lo + len(text) - len(text.lstrip()), lo + len(text.rstrip())
        for pattern in (_FLAG, _PICK):
            hit = pattern.fullmatch(clean, lo, hi)
            if not hit or hit['call'].split('(')[0].strip() in _NOT_CALLS:
                continue
            return lo, hi, hit
    return None


def _lines(hit, kind, local):
    call, op = hit['call'], hit['op']
    if hit.re is _FLAG:
        return [f'{kind} {local} = {call} {op} 0;']
    # `(f() ? a : b)`, `(f() != 0 ? a : b)` and `(f() == 0 ? a : b)`: the first constant is set, the second replaces it
    other = '!=' if op == '==' else '=='
    return [f'{kind} {local} = {hit["a"]};', f'if ({call} {other} 0) {{ {local} = {hit["b"]}; }}']


def _sites(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    words = set(re.findall(IDENT, clean))
    local = 'call_operand'
    while local in words:
        local += '_'
    found = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        if shut is None:
            continue
        lo = hit.end()
        hi = _first_operand(clean, lo, shut - 1)
        if hi == lo:
            continue
        operand = _operand(source, clean, lo, hi)
        end = _statement_end(clean, shut)
        if not operand or end is None:
            continue
        found.append((hit.start(), end, operand, local))
    return found


def _apply(source, site, kind):
    start, end, (lo, hi, hit), local = site
    indent = source[source.rfind('\n', 0, start) + 1:start]
    indent = indent[:len(indent) - len(indent.lstrip())]
    statement = source[start:lo] + local + source[hi:end]
    body = '\n'.join(f'{indent}    {line}' for line in _lines(hit, kind, local))
    return source[:start] + f'{{\n{body}\n{indent}    {statement}\n{indent}}}' + source[end:]


def _kinds(hit):
    cast = hit['cast']
    return (cast,) if cast else ('u32', 's32')


def variants(source, name):
    sites = _sites(source, name)
    if not sites:
        return []
    out = []
    if len(sites) > 1:
        for kind in ('u32', 's32'):
            # One at a time from the last: a wrapped test no longer matches, and a site in an `else` of another moves it.
            text, left, done = source, sites, 0
            while left and done < len(sites):
                text = _apply(text, left[-1], left[-1][2][2]['cast'] or kind)
                left, done = _sites(text, name), done + 1
            if done > 1:
                out.append((ALL, text))
    for site in sites:
        out.extend((FAMILY, _apply(source, site, kind)) for kind in _kinds(site[2][2]))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
