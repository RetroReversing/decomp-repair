"""A 64-bit value m2c read as two words: a `(0, 0)` argument pair, and a returned pair stored one word each.

    f(0, 0);                                            ->  ((void (*)()) f)(0ULL);
    t = f(); D_80000000 = t; D_80000004 = t;            ->  *(unsigned long long *) &D_80000000 = ((unsigned long long (*)()) f)();

**The argument.** `osSetTime(0)` passes one 64-bit zero in `$a0:$a1`. GCC 2.7.2 loads it with one two-instruction move, which
cannot fill the call's delay slot, so the last prologue save lands there instead of `move $a1, $zero`. Two `0` arguments are
two one-instruction moves, and the second takes the slot: the two spellings differ only in that order (1450 -> 300
-> 10 on a state machine at -O1, with its arms in order). Offered for a call statement whose arguments at an even
position (a 64-bit argument is aligned to an even register) are a literal `0` and a literal.

**The result.** The target stores `$v0` to a symbol and `$v1` to the word after it right after the call; m2c reads that
as one value stored twice (`$v1` as `$v0`'s variable), which stores `$v0` twice. Read from the target and rebuilt as one
64-bit store. A candidate rewrite; the exact judge decides.
"""
import re

from .call_site_prototype_repairs import split_args
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

ARGUMENT = 'wide_zero_argument'
RESULT = 'wide_return_store'
FAMILIES = (ARGUMENT, RESULT)

_LITERAL = re.compile(r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*')
_ZERO = re.compile(r'(?:0[xX]0+|0)[uUlL]*')
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else'}


def _stored(asm):
    """[(callee, symbol of $v0, symbol of $v1)] for each call whose result pair goes to two symbols straight after it."""
    rows = [' '.join(re.sub(r'/\*.*?\*/', '', line).split('#', 1)[0].split()) for line in asm.splitlines()]
    rows = [r for r in rows if r and not r.endswith(':')]
    out = []
    for i, row in enumerate(rows):
        call = re.fullmatch(rf'jal ({IDENT})', row)
        if not call:
            continue
        found = {}
        for after in rows[i + 2:i + 8]:
            if re.match(r'(?:j|jal|jr|b\w*)\b', after):
                break
            hit = re.fullmatch(rf'sw \$(v0|v1), %lo\(({IDENT})\)\(\$\w+\)', after)
            if hit:
                found.setdefault(hit[1], hit[2])
        if len(found) == 2:
            out.append((call[1], found['v0'], found['v1']))
    return out


def _declare(part, header, callee, kind):
    """The edit that declares `callee` before the function when neither the source nor the header does (a name the
    function only calls is implicitly declared, and cannot be cast), as `kind callee();`."""
    declaration = re.compile(rf'(?m)^[^\n=(){{}}#]*\b[\w*]+[ \t*]+{callee}\s*\([^;{{}}]*\)\s*[;{{]')
    if declaration.search(part.clean[:part.opening]) or declaration.search(header):
        return []
    start = part.clean.rfind('\n', 0, part.opening)
    while start > 0 and part.clean[:start].rstrip()[-1:] not in (';', '}', ''):
        start = part.clean.rfind('\n', 0, start)
    start = max(start + 1, 0)
    return [(start, start, f'extern {kind} {callee}();\n')]


def _arguments(part, header):
    out = []
    clean = part.clean
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', clean[part.opening:part.end]):
        if hit[1] in _KEYWORDS:
            continue
        at = part.opening + hit.start()
        if clean[:at].rstrip()[-1:] not in (';', '{', '}', ':', ')'):
            continue  # only a call statement: its result is not used
        paren = part.opening + hit.end() - 1
        after = close(clean, paren)
        if not after or not clean[after:].lstrip().startswith(';'):
            continue
        args = split_args(part.source[paren + 1:after - 1])
        for i in range(0, len(args) - 1, 2):
            if _ZERO.fullmatch(args[i]) and _LITERAL.fullmatch(args[i + 1]):
                low = args[i + 1].rstrip('uUlL')
                wide = args[:i] + [f'{low}ULL'] + args[i + 2:]
                text = f'((void (*)()) {hit[1]})({", ".join(wide)})'
                out.append((ARGUMENT, edit(part.source,
                                           _declare(part, header, hit[1], 'void') + [(at, after, text)])))
    return out


def _results(part, header, asm):
    out = []
    clean = part.clean
    # the target names a renamed callee by its address, so the pair is matched by its two symbols
    for first, second in dict.fromkeys((a, b) for _, a, b in _stored(asm)):
        word = r'(?:\(\*\([^()]*\*\)\s*&\s*{s}\)|\*\([^()]*\*\)\s*&\s*{s}|{s})'
        pattern = re.compile(
            rf'(?P<t>{IDENT})\s*=\s*(?:\([^()]*\)\s*)?(?P<f>{IDENT})\s*\(\s*\)\s*;\s*'
            rf'{word.format(s=first)}\s*=\s*(?:\([^()]*\)\s*)?(?P=t)\s*;\s*'
            rf'{word.format(s=second)}\s*=\s*(?:\([^()]*\)\s*)?(?P=t)\s*;')
        for hit in pattern.finditer(clean, part.opening, part.end):
            if len(re.findall(rf'\b{hit["t"]}\b', clean[hit.end():part.end])):
                continue  # the temporary is read again
            callee = hit['f']
            text = f'*(unsigned long long *) &{first} = ((unsigned long long (*)()) {callee})();'
            edits = _declare(part, header, callee, 'unsigned long long') + [(hit.start(), hit.end(), text)]
            out.append((RESULT, edit(part.source, edits)))
    return out


def variants(source, name, header='', asm=''):
    part = view(source, name)
    if not part:
        return []
    return _arguments(part, header) + (_results(part, header, asm) if asm else [])


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'archs': ('mips',)}
