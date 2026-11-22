"""A value computed before a branch that only one arm uses, sunk into that arm as its first statement in a one-shot scope.

`s32 inverse = ~mask;` before `if (tag == 45) {..} else {..}` where only the else arm reads `inverse` makes the pseudo
live across the branch (a global one: the allocator ranks it by `floor_log2(refs) * refs / live length`, last of the
function's locals, and gives it whatever register is left), while the target computed it inside the arm, where it is a
short-lived local that the block allocator places first and the delay slot of the branch picks up as the arm's first
instruction. Written as the arm's own first statement in `do { x = e; } while (0);` the first scheduler cannot hoist the
loads above it, so it stays first. A KMC GCC 2.7.2 N64 heap allocator (`-G0 -mips3 -mgp32 -mfp32 -O2`, 110
instructions, an alignment mask and its complement before a two-arm test) went 115 -> 85 on that edit alone (the
mask and the table offset exchanged their registers with the complement's, three rows of the arm's temporaries
remained); no existing family moves a declaration into an arm. The explanation is a hypothesis from the `-dl -dg`
tables and local-alloc.c, not confirmed in the compiler source.

`variants` first splits each block's initialised declarations (`local_weight_ladder.split_declarations`, no change to
the code: the arm's own loads then come after the sunk statement), then takes each plain assignment `x = e;` whose
expression names only locals and parameters (no memory, no call), whose variable is set once and read only inside one
brace arm of the next two-arm `if`, and offers the statement moved to the top of that arm: in the scope, and plain."""
import re

from .integer_repair_support import IDENT, edit, view
from .local_weight_ladder import _declaration, split_declarations, units

FAMILY = 'arm_invariant_sink'
FAMILIES = (FAMILY,)
LIMIT = 8
_ASSIGN_ONE = re.compile(rf'^(?P<x>{IDENT})\s*=(?!=)\s*(?P<e>[^=].*)$', re.S)
_CASTS = {'u8', 'u16', 'u32', 's8', 's16', 's32', 'int', 'char', 'short', 'long', 'unsigned', 'signed'}


def _close(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return -1


def _next_if(clean, start, limit):
    """(then_open, then_close, else_open, else_close) of the first `if (..) {..} else {..}` at the depth of `start`."""
    depth, index = 0, start
    while index < limit:
        char = clean[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and clean.startswith('if', index) and not re.match(r'\w', clean[index - 1:index] or ' ') \
                and re.match(r'if\s*\(', clean[index:index + 8]):
            paren = clean.index('(', index)
            level = 0
            for k in range(paren, limit):
                level += (clean[k] == '(') - (clean[k] == ')')
                if level == 0:
                    break
            then_open = clean.find('{', k)
            if then_open < 0 or clean[k + 1:then_open].strip():
                return None
            then_close = _close(clean, then_open)
            rest = clean[then_close + 1:].lstrip()
            if not rest.startswith('else'):
                return None
            else_open = clean.index('{', then_close)
            if clean[then_close + 1:else_open].strip() != 'else':
                return None
            return then_open, then_close, else_open, _close(clean, else_open)
        index += 1
    return None


def _first_statement(clean, opening, closing):
    """The offset of the first line of the arm that is not a plain declaration."""
    at = opening + 1
    for line in clean[opening + 1:closing].split('\n')[1:]:
        at += len(clean[at:].split('\n', 1)[0]) + 1
        if not _declaration(line):
            break
    return at


def variants(source, name):
    base = split_declarations(source, name)
    part = view(base, name)
    found, tracked = units(base, name)
    if not part or not found:
        return []
    clean = part.clean
    result = []
    for start, end, text, counts in found:
        match = _ASSIGN_ONE.match(text.strip().rstrip(';').strip())
        if not match or match['x'] not in tracked:
            continue
        x, expr = match['x'], match['e']
        words = set(re.findall(IDENT, expr)) - _CASTS
        if not words or not words <= tracked or re.search(r'[\[\]*]|->|\.|\+\+|--|\(\s*\)', expr) or x in words:
            continue
        if len(re.findall(rf'(?<![\w.>]){re.escape(x)}\s*=(?!=)', clean[part.opening:part.end])) != 1 \
                or re.search(rf'[(,=]\s*&\s*{re.escape(x)}\b', clean[part.opening:part.end]):
            continue
        arms = _next_if(clean, end, part.end)
        if not arms:
            continue
        then_open, then_close, else_open, else_close = arms
        block_end = then_open
        uses = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(x)}\b', clean[end:part.end])]
        uses = [end + u for u in uses]
        inside = [u for u in uses if then_open < u < then_close], [u for u in uses if else_open < u < else_close]
        if not uses or len(inside[0]) + len(inside[1]) != len(uses) or (inside[0] and inside[1]):
            continue
        if any(re.search(rf'(?<![\w.>]){re.escape(w)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{re.escape(w)}|{re.escape(w)}\s*\+\+',
                         clean[end:block_end]) for w in words):
            continue
        opening, closing = (then_open, then_close) if inside[0] else (else_open, else_close)
        line_start = base.rfind('\n', 0, start) + 1
        line_end = base.find('\n', end)
        indent = re.match(r'[ \t]*', base[line_start:start])[0]
        arm_indent = re.match(r'[ \t]*', base[base.find('\n', opening) + 1:])[0] or indent + '    '
        declared = re.search(rf'(?m)^[ \t]*((?:{IDENT}[ \t]+)*{IDENT}[ \t]*\**[ \t]*){re.escape(x)}[ \t]*;', clean[part.opening:part.end])
        if not declared:
            continue
        declaration = f"{arm_indent}{declared[1].rstrip() + (' ' if not declared[1].rstrip().endswith('*') else '')}{x};\n"
        assignment = f"{expr.strip()}"
        first = _first_statement(clean, opening, closing)
        for scoped in (True, False):
            body = f"do {{ {x} = {assignment}; }} while (0);" if scoped else f"{x} = {assignment};"
            changes = [(line_start, line_end + 1, ''), (opening + 1, opening + 1, '\n' + declaration.rstrip('\n')),
                       (first, first, f"{arm_indent}{body}\n")]
            decl_line = re.search(rf'(?m)^[ \t]*(?:{IDENT}[ \t]+)*{IDENT}[ \t]*\**[ \t]*{re.escape(x)}[ \t]*;[ \t]*\n', base[part.opening:part.end])
            if decl_line:
                at = part.opening + decl_line.start()
                changes.append((at, at + len(decl_line[0]), ''))
            result.append((FAMILY, edit(base, changes)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)
