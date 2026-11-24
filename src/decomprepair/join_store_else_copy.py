"""The statement after an `if` whose arm calls, copied into that arm and into a new `else`: `if (c) { f(); } *p = 4;` as
`if (c) { f(); *p = 4; } else { *p = 4; }`.

KMC GCC 2.7.2 (`-O2`, N64) runs cse along a path that skips a block jumped around (`flag_cse_skip_blocks`,
cse.c `cse_end_of_basic_block`): after `if (t != 0xFF) { setSlot(t, ..); } *cmd = 4; r = update(v, &G);` it still knows
the register that held `&G` for a load before the `if`, so the call argument `&G` becomes a copy of that register, which
is then live across `setSlot` and takes a saved register (`la $s0` before the branch, `move $a1, $s0` at the call). A
target that loads `lui $a1; addiu $a1, %lo(G)` at the call again had the join start a block of its own: with the store
written in both arms, the join label after them is reached from two places and cse starts afresh there; the final
jump pass cross-jumps the two copies of the store back into one (the target's `addiu $v0, $zero, 4` twice, once in the
branch's delay slot). On a 1315-instruction sound-sequence interpreter's pan command, 5025 -> 4645. The cse reading is
a hypothesis from the output and cse.c; the judge decides.

Rewrites an `if (..) { .. }` with no `else` whose arm holds a call and falls through, followed by one simple statement
without a call (`*p = K;`, `x = y;`, a field store), which is followed by a statement that calls. Bounded to `LIMIT`
children, one site each.
"""
import re

from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'join_store_else_copy'
FAMILIES = (FAMILY,)
LIMIT = 6

CALL = re.compile(r'\b(?!(?:if|while|for|switch|return|sizeof)\b)[A-Za-z_]\w*\s*\(')
CAST = re.compile(r'\(\s*(?:(?:unsigned|signed|const|volatile|struct)\s+)*[A-Za-z_]\w*\s*\**\s*\)')
SIMPLE = re.compile(r'[ \t]*[^;{}\n]*[^=!<>]=(?!=)[^;{}\n]*;[ \t]*\n')


def _calls(text):
    return CALL.search(CAST.sub(' ', text)) is not None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    out = []
    for found in re.finditer(r'\bif\s*\(', clean[lo:hi]):
        start = lo + found.start()
        cond_end = close(clean, lo + found.end() - 1)
        if not cond_end:
            continue
        arm = re.compile(r'\s*\{').match(clean, cond_end)
        if not arm:
            continue
        a = arm.end() - 1
        b = close(clean, a, '{', '}')
        if not b:
            continue
        body = clean[a + 1:b - 1]
        if re.compile(r'\s*else\b').match(clean, b) or not _calls(body):
            continue
        if re.search(r'\b(?:return|goto|break|continue)\b[^;]*;\s*$', body):
            continue  # the arm does not reach the join
        line_end = clean.find('\n', b)
        if line_end < 0 or clean[b:line_end].strip():
            continue
        stmt = SIMPLE.match(clean, line_end + 1)
        if not stmt:
            continue
        text = clean[stmt.start():stmt.end()]
        if _calls(text) or re.match(r'\s*(?:if|for|while|do|switch|return|case|default)\b', text) or ':' in text:
            continue
        follow = clean[stmt.end():clean.find(';', stmt.end()) + 1]
        if not _calls(follow):
            continue
        indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, start) + 1:]).group(0)
        arm_indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, b - 1) + 1:]).group(0)
        inner = arm_indent + '  ' if clean[b - 1] == '}' and clean.rfind('\n', 0, b - 1) >= a else indent + '  '
        statement = source[stmt.start():stmt.end()].strip()
        arm_text = source[a:b - 1].rstrip() + '\n' + inner + statement + '\n' + source[clean.rfind('\n', 0, b - 1) + 1:b]
        child = (source[:a] + arm_text + '\n' + arm_indent + 'else\n' + arm_indent + '{\n' + inner + statement + '\n'
                 + arm_indent + '}\n' + source[stmt.end():])
        out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
