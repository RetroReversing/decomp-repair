"""A word local assigned from a chain of integer operations, written one operation per statement into the local.

`v = (((b - a) * t) >> 12) + a;` against `v = b - a; v *= t; v >>= 12; v += a;`. The one-expression form inlined from a
helper (a fixed-point interpolation) left the difference and the product in `$v0` and only the last sum in the local;
the target had `subu $a1`, `mflo $a1`, `sra $a1,$a1,12` and `addu $a1,$a1,$a0`, the local's own register from the first
step. The local was reused later in the function (a colour clamp), so it was one pseudo living across blocks, and
every intermediate written into it was that pseudo. A 170-instruction N64 keyframe routine (SN64 GCC `sn-n64-281`,
`-G0 -mips3 -O2 -mfp64`) was 80 -> 0 on this one rewrite. `float_chain_stage` is the same step for floats only, and
`compound_operand_split` takes one operator and, for integers, only bitwise ones. Hypothesis (not read in the
compiler's source): local-alloc ties each temporary to a dying operand's register, which a global local is not.

Children, for a 32-bit signed local (`s32`, `int`) assigned from a left-leaning chain of two or more binary
`+ - * << >> & | ^` operations whose later operands do not mention it: `v = first op second; v op= next; ...`, each
statement on its own and every such statement of the function together. An operand may call only a `static inline`
helper of the source that does nothing but return an expression (a pure read). A chain with anything unsigned in it is
left alone (a right shift would change its value), as is a statement under an unbraced `if` and a function with
`volatile`. A `(s32)` cast around part of the chain is dropped, being the type it already has. Only MIPS. The candidate
is never a verdict: the judge decides.
"""
import re

from .c_scan import _close
from .csource import _blank, find

FAMILY = 'integer_chain_stage'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_LIMIT = 16
_STATEMENT = re.compile(rf'(?<=[;{{}}])(\s*)({_ID})\s*=(?![=])\s*([^;{{}}=]+);')
_SIGNED = re.compile(r'\b(?:s32|int|signed\s+int)\b([^;(){}]*);')
_UNSIGNED_DECL = re.compile(r'\b(?:u8|u16|u32|u64|unsigned(?:\s+(?:char|short|int|long))?)\b[\s*]+(' + _ID + ')')
_UNSIGNED = re.compile(r'\b(?:u32|u64|size_t)\b|\bunsigned\b|\b(?:0x[0-9A-Fa-f]+|\d+)[uU][lL]*\b')
_CAST = re.compile(r'\(\s*(?:s32|int)\s*\)\s*(?=\()')
_PURE = re.compile(rf'\bstatic\s+(?:__inline__|inline)\s+(?:s8|s16|s32|int)\s+({_ID})\s*\([^()]*\)\s*\{{\s*'
                   r'return\b([^;{}]*);\s*\}')
# operator levels, loosest first
_LEVELS = (('|',), ('^',), ('&',), ('<<', '>>'), ('+', '-'), ('*',))
_BINARY = {op for level in _LEVELS for op in level}
_CASTS = re.compile(rf'\(\s*(?:(?:struct\s+)?{_ID}[\s*]*\*|s8|s16|s32|u8|u16|int|short|char)\s*\)(?=\s*[\w(*&-])')
_GROUP = re.compile(r'\([^()\[\]]*\)|\[[^()\[\]]*\]')
_TOKEN = re.compile(r'<<=?|>>=?|->|&&|\|\||[=!<>]=|\+\+|--|[-+*/%&|^<>?:=!,~]')


def _signed_names(text):
    out = set()
    for hit in _SIGNED.finditer(text):
        if re.search(r'\bunsigned\s*$', text[:hit.start()]):
            continue
        for part in hit[1].split(','):
            name = part.split('=')[0].strip()
            if re.fullmatch(_ID, name):
                out.add(name)
    return out


def _unwrap(text):
    """`text` without outer parentheses and without a `(s32)` cast of a whole parenthesised group."""
    text = text.strip()
    while True:
        if text.startswith('(') and _close(text, 0, '(', ')') == len(text) - 1:
            text = text[1:-1].strip()
            continue
        cast = _CAST.match(text)
        if cast and _close(text, cast.end(), '(', ')') == len(text) - 1:
            text = text[cast.end():]
            continue
        return text


def _mask(expr):
    """`expr` at the same length with casts blanked and every bracketed group filled, so what is left is depth 0."""
    text = _CASTS.sub(lambda hit: ' ' * len(hit[0]), expr)
    found = 1
    while found:
        text, found = _GROUP.subn(lambda hit: '_' * len(hit[0]), text)
    return text


def _split(expr):
    """(left, op, right) at the last of the loosest-binding binary operators at depth 0, else None."""
    masked = _mask(expr)
    found = []
    for hit in _TOKEN.finditer(masked):
        token = hit[0]
        if token == '->':
            continue
        binary = re.search(r'\w\s*$', masked[:hit.start()])
        if token not in _BINARY:
            if token in ('~', '!') or (token == '-' and not binary):
                continue
            return None
        if binary:
            found.append((hit.start(), token))
        elif token not in ('-', '+', '*', '&'):
            return None
    for level in _LEVELS:
        at = [(i, op) for i, op in found if op in level]
        if at:
            i, op = at[-1]
            return expr[:i].strip(), op, expr[i + len(op):].strip()
    return None


def _pure(operand, helpers):
    """Whether `operand` has no side effect: no assignment, and no call except to a return-only helper."""
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\?', operand):
        return False
    for hit in re.finditer(rf'({_ID})\s*\(', operand):
        if hit[1] not in helpers and hit[1] not in ('sizeof', 's8', 's16', 's32', 'u8', 'u16'):
            return False
    return True


def _chain(expr, name, helpers):
    """[first operand, (op, right), ...] of a chain of 2+ operations, else None."""
    steps, current = [], _unwrap(expr)
    while True:
        parts = _split(current)
        if not parts:
            break
        left, op, right = parts
        if re.search(rf'\b{name}\b', right) or not _pure(right, helpers):
            return None
        steps.append((op, _unwrap(right)))
        current = _unwrap(left)
    if len(steps) < 2 or not _pure(current, helpers):
        return None
    if current != name and re.search(rf'\b{name}\b', current):
        return None
    return [current, *reversed(steps)]


def _operand(text):
    return text if re.fullmatch(rf'-?[\w.]+|{_ID}(?:->{_ID}|\.{_ID}|\[[^\[\]]*\]|\([^()]*\))*', text) else f'({text})'


def _staged(name, chain, indent):
    first, (op, right), *rest = chain
    lines = [f'{name} = {_operand(first)} {op} {_operand(right)};']
    lines += [f'{name} {op}= {right};' for op, right in rest]
    return f'\n{indent}'.join(lines)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    body = clean[span[0]:span[1]]
    if opening < 0 or re.search(r'\bvolatile\b', body):
        return []
    names = _signed_names(body)
    unsigned = set(_UNSIGNED_DECL.findall(clean))
    helpers = {hit[1] for hit in _PURE.finditer(clean) if _pure(hit[2], ()) and not _UNSIGNED.search(hit[2])}
    found = []
    for hit in _STATEMENT.finditer(clean, opening, span[1]):
        var, rhs = hit[2], hit[3]
        if var not in names or _UNSIGNED.search(rhs) or unsigned & set(re.findall(_ID, rhs)):
            continue
        chain = _chain(rhs, var, helpers)
        if chain:
            found.append((hit.start(2), hit.end(), var, chain, hit[1].split('\n')[-1]))
    found = found[:_LIMIT]
    out = [source[:start] + _staged(var, chain, indent) + source[end:]
           for start, end, var, chain, indent in found]
    if len(found) > 1:
        joined = source
        for start, end, var, chain, indent in reversed(found):
            joined = joined[:start] + _staged(var, chain, indent) + joined[end:]
        out.append(joined)
    return [(FAMILY, child) for child in out if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
