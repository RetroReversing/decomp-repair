"""A call's pointer result copied into a second local at the top of the non-null guard that follows it.

The game's source often has two pointers where m2c has one: `p = alloc(); *slot = p; if (p != NULL) { q = p; ...q->a...; q->b...}`.
With one local the pointer lives in `$s0` from the call to the last store, and the `beqz $v0` and the store of the result use
`$s0`; the target tests and stores `$v0` straight from the call and moves it into the saved register inside the guard (`move
$s0, $v0` in the delay slot of the first call there). A KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) player-update routine
of 1137 instructions went 2451 -> 2321 with the copy; one step of a chain that ended 60 from a match. The allocation reason
(two pseudos, the first block-local in `$v0`) is a hypothesis; the judge decides.

guarded_call_result_copy
    `T = f(...);` followed (directly, or after statements that do not mention T's guard) by `if (T != NULL) {` / `if (T != 0) {`
    / `if (T) {` whose braced body mentions T at least twice: one child declares `P` of T's pointer type, writes `P = T;`
    as the body's first statement and reads P for every mention of T in the body. T must be a declared pointer local and
    not be written in the body. One child per call, at most 4."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILY = 'guarded_call_result_copy'
FAMILIES = (FAMILY,)
LIMIT = 4
_CALL = re.compile(rf'(?<![\w.>])(?P<var>{IDENT})\s*=\s*{IDENT}\s*\([^;{{}}]*\)\s*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    out = []
    for call in _CALL.finditer(clean, opening, span[1]):
        var = call['var']
        declared = re.search(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w \t]*?\*)[ \t]*{var}[ \t]*;', clean[opening:call.start()])
        if not declared:
            continue
        guard = re.compile(rf'\bif\s*\(\s*(?:{var}\s*!=\s*(?:NULL|0)|{var})\s*\)\s*\{{').search(clean, call.end(), min(span[1], call.end() + 700))
        if not guard:
            continue
        # nothing between the call and the guard may open another block (the guard must follow the call at one nesting level)
        if re.search(r'[{}]', clean[call.end():guard.start()]):
            continue
        open_at = guard.end() - 1
        stop = close(clean, open_at, '{', '}')
        if not stop:
            continue
        body = clean[open_at + 1:stop - 1]
        uses = list(re.finditer(rf'(?<![\w.>]){var}\b', body))
        if len(uses) < 2 or re.search(rf'(?<![\w.>]){var}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|&\s*{var}\b|\+\+\s*{var}|{var}\s*\+\+', body):
            continue
        copy = f'{var}_copy'
        if re.search(rf'\b{copy}\b', clean):
            continue
        text = source
        for use in reversed(uses):
            text = text[:open_at + 1 + use.start()] + copy + text[open_at + 1 + use.end():]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, guard.start()) + 1:])[0] + '  '
        text = text[:open_at + 1] + f'\n{indent}{copy} = {var};' + text[open_at + 1:]
        decl_line = source.rfind('\n', 0, opening + 1 + declared.start()) + 1
        line_end = source.find('\n', opening + declared.start() + 1) + 1
        decl_indent = re.match(r'[ \t]*', source[decl_line:])[0] or indent
        text = text[:line_end] + f'{decl_indent}{re.sub(r"\s+", " ", declared["type"].strip())}{copy};\n' + text[line_end:]
        out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
