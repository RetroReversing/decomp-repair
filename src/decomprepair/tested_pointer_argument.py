"""A pointer the code has just tested through, passed on to a call as one more argument.

A target can hold a just-loaded pointer in `$a1` while it reads a byte through it (`lw $a1, 0($s0); lbu $v0, 0($a1)`)
where ours uses `$v0`: a later call named that pointer as its second argument, though the callee reads none of it (a
retail stub, an unprototyped call). The value is already in the register, so the call site shows no move. On an N64
asset list loop (SN GCC 2.8.1, `-G0 -mips3 -O2`) `stub(path);` written `stub(path, names.p[i]);` after
`if (*names.p[i] == ' ')` was the last two rows (judged 10 to exact). The o32 callee ignores extra arguments.

For each `*E == ..` or `E[0] == ..` test it offers, for each call written after it whose callee the source declares
with integer or pointer parameters, the call with `E` appended and the declaration left unprototyped.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'tested_pointer_argument'
FAMILIES = (FAMILY,)
LIMIT = 12

_PART = r'(?:\.\w+|->\w+|\[\w+\])'
_TEST = re.compile(r'\bif\s*\(\s*(?:\*\s*(?P<star>[A-Za-z_]\w*' + _PART + r'*)|(?P<index>[A-Za-z_]\w*' + _PART
                   + r'*)\[0\])\s*[!=]=')
_CALL = re.compile(r'\b(?P<callee>[A-Za-z_]\w*)\s*\(')
_FLOAT = re.compile(r'\b(?:f32|f64|float|double)\b|\.\.\.')


def _declaration(clean, callee, end):
    """The match of the callee's prototype before the function, its parameter list in group `params`."""
    return re.search(rf'(?m)^[ \t]*(?:extern[ \t]+)?[A-Za-z_][\w \t]*[ \t*]\b{callee}[ \t]*\((?P<params>[^()]*)\)[ \t]*;',
                     clean[:end])


def variants(source, name, arch='', limit=LIMIT):
    if arch and not arch.startswith('mips'):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    brace = clean.find('{', span[0], span[1])
    end = close(clean, brace, '{', '}') if brace >= 0 else None
    if not end:
        return []
    out, seen = [], set()
    for test in _TEST.finditer(clean, brace, end):
        value = test['star'] or test['index']
        for call in _CALL.finditer(clean, test.end(), end):
            declared = _declaration(clean, call['callee'], span[0])
            if not declared or declared['params'].strip() in ('', 'void') or _FLOAT.search(declared['params']):
                continue
            stop = close(clean, call.end() - 1, '(', ')')
            if not stop:
                continue
            args = source[call.end():stop - 1].strip()
            if not args or value in args or (call.start(), value) in seen:
                continue
            seen.add((call.start(), value))
            text = source[:stop - 1] + ', ' + value + source[stop - 1:]
            text = text[:declared.start('params')] + text[declared.end('params'):]
            out.append((FAMILY, text))
            if len(out) >= limit:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 60}
