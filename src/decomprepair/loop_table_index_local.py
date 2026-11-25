"""A table read inside a loop whose index is an expression, with the index named in a local first.

m2c writes a read of a global table as `*((u8 *) (((char *) (&D)) + (EXPR)))`. When EXPR is a register (a counter), the
address `(plus (reg) (symbol_ref D))` is a legitimate MIPS address and the target keeps the symbol in the load
(`lui $v0, %hi(D); addu $v0, $v0, $idx; lbu $v0, %lo(D)($v0)`). When EXPR is a computation (`layer * 0xA0`), the
expansion cannot add a symbol to a non-register operand, so it loads the symbol into a pseudo of its own first; that
pseudo is set once inside the loop and loop.c moves it out (`lui $t1, %hi(D); addiu $t1, $t1, %lo(D)` before the loop,
`addu $v1, $v1, $t1; lbu $v0, ($v1)` in it), taking a register the target does not spend and moving every constant the
loop hoists after it. Hypothesis from the dumps (loop.c's movable list shows the `symbol_ref` set, `-dL`), not from
expr.c's source.

Named in a local first (`idx = EXPR; ... *((u8 *) (((char *) (&D)) + idx))`) the address is `(plus (reg) (symbol_ref))`
again, nothing is hoisted and the target's three instructions come back. A 1133-instruction effect spawner (KMC GCC
2.7.2) went 1875 -> 840 with this one edit, after three spellings of the read itself (`(&D)[i]`, `D[i]` with an array
declaration, the cast form) had compiled identically.

The local is declared at the top of the function and assigned just before the statement that reads the table; reads
whose statement follows an `else` (an `else if`) are left alone, as are indexes with calls, assignments or `++`/`--`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loop_table_index_local'
FAMILIES = (FAMILY,)
LIMIT = 6

READ = re.compile(r'\*\s*\(\(\s*[A-Za-z_][\w \t]*?\s*\*\s*\)\s*\(\(\(\s*(?:unsigned\s+)?char\s*\*\s*\)\s*\(\s*&\s*'
                  r'(?P<sym>[A-Za-z_]\w*)\s*\)\s*\)\s*\+\s*')


def _python_blocks(clean, start, end):
    stack, found = [], []
    for position in range(start, end):
        if clean[position] == '{':
            stack.append(position)
        elif clean[position] == '}' and stack:
            found.append((stack.pop(), position))
    return found


_blocks = _python_blocks
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _blocks(clean, start, end):
        found = _scan.block_pairs(clean, start, end)
        return _python_blocks(clean, start, end) if found is NotImplemented else found


def _is_loop_body(clean, opening):
    head = clean[:opening].rstrip()
    return head.endswith('do') or bool(re.search(r'\b(?:for|while)\s*\([^{};]*\)$', head))


def _statement_start(body, at):
    depth, start = 0, 0
    for i, ch in enumerate(body[:at]):
        depth += (ch == '(') - (ch == ')')
        if depth == 0 and ch in ';{}':
            start = i + 1
    return start


def _python_index_end(clean, at):
    """The end of EXPR in `(((char *) (&D)) + EXPR)`: where the group opened before `((char *)` closes."""
    depth = 1
    for i in range(at, len(clean)):
        if clean[i] == '(':
            depth += 1
        elif clean[i] == ')':
            depth -= 1
            if depth == 0:
                return i
        elif clean[i] in ';{}':
            return None
    return None


_index_end = _python_index_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _index_end(clean, at):
        found = _scan.index_end(clean, at)
        return _python_index_end(clean, at) if found is NotImplemented else found


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    loops = [(a, b) for a, b in _blocks(clean, opening + 1, end - 1) if _is_loop_body(clean, a)]
    result, seen = [], set()
    for hit in READ.finditer(clean, opening, end):
        if not any(a < hit.start() < b for a, b in loops):
            continue
        stop = _index_end(clean, hit.end())
        if stop is None:
            continue
        index = source[hit.end():stop].strip()
        if (not re.search(r'[-+*/<>&|^%]', index) or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', index)
                or re.search(r'\b[A-Za-z_]\w*\s*\(', index)):
            continue  # a plain register already makes the target's address; side effects stay where they are
        local = '__index_' + hit['sym']
        if re.search(r'\b' + re.escape(local) + r'\b', source) or (hit['sym'], index) in seen:
            continue
        seen.add((hit['sym'], index))
        at = opening + 1 + _statement_start(clean[opening + 1:hit.start()], hit.start() - opening - 1)
        at += len(re.match(r'\s*', clean[at:])[0])
        if re.search(r'\belse\s*$', clean[:at]) or re.match(r'else\b', clean[at:]) or at >= hit.start():
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:at])[0]
        text = source[:hit.end()] + local + source[stop:]
        text = text[:at] + f'{local} = {index};\n{indent}' + text[at:]
        text = text[:opening + 1] + f'\n  s32 {local};' + text[opening + 1:]
        result.append((FAMILY, text))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
