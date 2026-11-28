"""Move a shared call into both arms of an adjacent conditional assignment.

The assignment stays in its original arm, so later uses retain the same value. Nested one-shot wrappers around a
single call may be removed. In a MIPS audio dispatcher this changed the conditional call layout from 1211 to 881.
"""
import re

from .arm_block_support import brace_pairs, statements
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'conditional_call_branch'
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
SELECT = re.compile(r'if\s*\(\s*(?P<cond>' + IDENT + r')\s*\)\s*'
                    r'(?P<assign>' + IDENT + r'\s*=\s*' + NUMBER + r'\s*;)\s*\Z')
CALL = re.compile(IDENT + r'\s*\(')
DO = re.compile(r'do\s*\{')


def _call(clean, start, end, depth=0):
    """The direct call inside only one-shot wrappers, or None."""
    if depth > 12:
        return None
    leading = re.match(r'\s*', clean[start:end])
    at = start + leading.end()
    wrapper = DO.match(clean, at, end)
    if wrapper:
        opening = wrapper.end() - 1
        closing = close(clean, opening, '{', '}')
        if not closing or closing > end or not re.fullmatch(r'\s*while\s*\(\s*0[uUlL]*\s*\)\s*;\s*', clean[closing:end]):
            return None
        return _call(clean, opening + 1, closing - 1, depth + 1)
    call = CALL.match(clean, at, end)
    if not call or call[0].split('(')[0].strip() in ('if', 'while', 'for', 'switch', 'sizeof'):
        return None
    closing = close(clean, call.end() - 1)
    if not closing or closing > end or not re.fullmatch(r'\s*;\s*', clean[closing:end]):
        return None
    return at, closing + len(re.match(r'\s*;', clean[closing:end])[0])


def _integer_condition(text, name):
    """`name` is a declared integer, so testing it against zero preserves `if (name)`."""
    types = ('s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'short', 'char')
    decl = re.compile(r'\b(' + IDENT + r')\s+' + re.escape(name) + r'\s*(?=[,;=)])')
    kinds = [found[1] for found in decl.finditer(text)]
    if not kinds or any(kind not in types for kind in kinds):
        return False
    if re.search(r'\b' + IDENT + r'\s*\*+\s*' + re.escape(name) + r'\b', text):
        return False
    for kind in set(kinds) & {'s8', 'u8', 's16', 'u16', 's32', 'u32'}:
        if not re.search(r'\btypedef\s+(?:signed|unsigned)\s+(?:char|short|int)\s+'
                         + re.escape(kind) + r'\s*;', text):
            return False
    return True


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    if re.search(r'\b__(?:LINE|COUNTER)__\b', header + '\n' + source):
        return []
    if re.search(r'^\s*#|\b(?:asm|__asm__|setjmp|longjmp)\b', clean[span[0]:span[1]], re.M):
        return []
    pairs = brace_pairs(clean, span[0], span[1])
    if not pairs:
        return []
    declarations = _blank(header + '\n' + source)
    macros = set(re.findall(r'^\s*#\s*define\s+(' + IDENT + r')\b', declarations, re.M))
    out = []
    for opening, closing in pairs.items():
        siblings = statements(clean, opening + 1, closing)
        for first, second in zip(siblings, siblings[1:]):
            a, b = first
            c, d = second
            selected = SELECT.fullmatch(clean[a:b])
            call = _call(clean, c, d)
            if not selected or not call or source[b:c].strip() or re.search(r'/\*|//', source[a:d]):
                continue
            call_text = source[call[0]:call[1]]
            if macros.intersection(re.findall(IDENT, clean[a:b] + clean[call[0]:call[1]])):
                continue
            condition = selected['cond']
            if not _integer_condition(declarations, condition):
                continue
            assignment = source[a + selected.start('assign'):a + selected.end('assign')]
            indent = re.search(r'[ \t]*$', source[:a])[0]
            replacement = (f'if ({condition} == 0) {{\n{indent}    {call_text}\n{indent}}} else {{\n'
                           f'{indent}    {assignment}\n{indent}    {call_text}\n{indent}}}')
            out.append((FAMILY, source[:a] + replacement + source[d:]))
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
