"""call_result_join_copy: a call's pointer result copied into a local of its own after the first join, one child.

The target of a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) menu function keeps TWO pseudos for the one pointer a call
returns: `move $a0,$v0` (stored to a global) and, after an `if` block, `move $a2,$a0` (the copy the later field stores go
through). m2c writes one local (`temp_v0_2`) for both, so the source has one pseudo and the second move is never made; the
branch that follows the copy then loses its delay-slot filler, and `reorg` writes `bnel` where the target has `beqz` + `j`
(470 -> 60 on a 118-instruction function, the rest of the difference being a scheduling order).

  - a copy placed right after the call is folded back into the call's own set by `combine` (same basic block: no extra
    move); it has to come after a join, so the copy's source is live across a branch and is a pseudo of its own;
  - the copy has to be read after the join and the original has to be read before the copy (a store to a global): a
    copy whose source dies in it is tied to it by `local-alloc`/`global.c`'s copy preference and the move is deleted;
  - m2c passes the carrier pointer on as a trailing argument of a callee that reads fewer (`f(obj, 1, item)` where every
    other caller of `f` passes two): that third argument keeps the original live to the end of the function, so alone the
    copy scores 80 and with the argument dropped (the prototype's last parameter too) 60. The argument is a guess
    that only the judge can confirm (a callee that does read it makes the child worse, never a false match).

Hypotheses from `global.c`/`local-alloc.c`, measured on one function; the exact judge decides. The shape: a function
(no goto, switch or loop) with a pointer local assigned once from a call, a plain use of it before the first `if`
statement that follows, and uses after that `if`. One child renames every later use, one only the member accesses, and
one renames every later use and drops the trailing carrier argument from calls whose prototype is declared in the source.
"""
import re

from .call_carrier_pointer_split import IDENT, POINTER_DECL, UNORDERED, _arguments, _params
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'call_result_join_copy'
DEREF_FAMILY = 'call_result_join_copy_deref'
DROP_FAMILY = 'call_result_join_copy_drop'
FAMILIES = (FAMILY, DEREF_FAMILY, DROP_FAMILY)

MAX_JOINS = 3
ASSIGN = re.compile(rf'(?s)\A[ \t\n]*({IDENT})[ \t]*=(?!=)([^;]*\([^;]*);\Z')
ELSE = re.compile(r'else(?![\w])')
IF = re.compile(r'if\s*\(')


def _skip(clean, index):
    while index < len(clean) and clean[index].isspace():
        index += 1
    return index


def _statement_end(clean, index, limit):
    """The position just past the statement that starts at `index` (an `if` chain, a block or a plain statement)."""
    if index >= limit:
        return None
    hit = IF.match(clean, index)
    if hit:
        after = close(clean, hit.end() - 1, '(', ')')
        then_end = _statement_end(clean, _skip(clean, after), limit) if after else None
        if then_end is None:
            return None
        other = ELSE.match(clean, _skip(clean, then_end))
        if other:
            return _statement_end(clean, _skip(clean, other.end()), limit)
        return then_end
    if clean[index] == '{':
        return close(clean, index, '{', '}')
    depth = 0
    for position in range(index, limit):
        char = clean[position]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char in '{}':
            return None
        elif char == ';' and depth == 0:
            return position + 1
    return None


def _statements(clean, start, end):
    """(start, end) of each statement of the block whose body is clean[start:end]."""
    spans, index = [], _skip(clean, start)
    while index < end:
        stop = _statement_end(clean, index, end)
        if stop is None:
            return None
        spans.append((index, stop))
        index = _skip(clean, stop)
    return spans


def _blocks(clean, start, end):
    """Every statement list under clean[start:end]: the block itself, then the braced bodies inside its statements."""
    spans = _statements(clean, start, end)
    if spans is None:
        return []
    found = [spans]
    for first, last in spans:
        position = first
        while True:
            opening = clean.find('{', position, last)
            if opening < 0:
                break
            closing = close(clean, opening, '{', '}')
            if not closing or closing > last:
                break
            found.extend(_blocks(clean, opening + 1, closing - 1))
            position = closing
    return found


def _uses(text, local):
    return list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', text))


def _fresh(clean, local):
    fresh = f'{local}_copy'
    while re.search(rf'\b{fresh}\b', clean):
        fresh += '_'
    return fresh


def _prototype(clean, part, callee):
    """The (parameter list start, end) of `callee`'s declaration before the function, or None."""
    for hit in re.finditer(rf'(?m)^[^\n;{{}}()]*\b{re.escape(callee)}\s*\(', clean[:part.opening]):
        end = close(clean, hit.end() - 1, '(', ')')
        if end and re.match(r'\s*;', clean[end:end + 8]):
            return hit.end(), end - 1
    return None


def _drops(clean, part, ranges, local):
    """Edits that remove the trailing `local` argument from each call in `ranges` and the callee's last parameter."""
    edits, shrunk = [], set()
    for start, end in ranges:
        for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', clean[start:end]):
            callee = hit[1]
            if callee in ('if', 'while', 'for', 'switch', 'return', 'sizeof'):
                continue
            opening = start + hit.end() - 1
            closing = close(clean, opening, '(', ')')
            if not closing:
                continue
            spans = _arguments(clean, opening + 1, closing - 1)
            if len(spans) < 2 or clean[spans[-1][0]:spans[-1][1]].strip() != local:
                continue
            prototype = _prototype(clean, part, callee)
            if not prototype:
                continue
            declared = _arguments(clean, prototype[0], prototype[1]) if clean[prototype[0]:prototype[1]].strip() else []
            if declared and (len(declared) != len(spans) or any(ch in clean[a:b] for a, b in declared for ch in '()')):
                continue
            edits.append((spans[-2][1], spans[-1][1], ''))
            if declared and callee not in shrunk:
                shrunk.add(callee)
                edits.append((declared[-2][1], declared[-1][1], ''))
    return edits


def variants(source, name):
    part = view(source, name)
    if not part or UNORDERED.search(part.body):
        return []
    clean = part.clean
    params = _params(clean, part)
    pointers = {}
    for hit in POINTER_DECL.finditer(clean, part.opening + 1, part.end):
        local = hit[4]
        if local not in params and local not in pointers:
            pointers[local] = (hit[1], hit[2], hit[3], hit.end())
    if not pointers:
        return []
    out = []
    body_end = clean.rfind('}', part.opening, part.end)
    for spans in _blocks(clean, part.opening + 1, body_end):
        for index, (first, last) in enumerate(spans):
            match = ASSIGN.match(clean[first:last])
            if not match or match[1] not in pointers:
                continue
            local = match[1]
            if len(re.findall(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', clean[part.opening:part.end])) != 1:
                continue
            block_end = spans[-1][1]
            if _uses(clean[block_end:body_end], local):
                continue  # a read after the block would see the original on a path the copy never ran on
            joins = [(a, b) for a, b in spans[index + 1:] if IF.match(clean, a)]
            for join in joins[:MAX_JOINS]:
                if not _uses(clean[last:join[0]], local) or not _uses(clean[join[1]:block_end], local):
                    continue
                indent, kind, stars, declaration_end = pointers[local]
                copy = _fresh(clean, local)
                rest = [(join[1] + u.start(), join[1] + u.end()) for u in _uses(clean[join[1]:block_end], local)]
                line = clean.rfind('\n', 0, join[0]) + 1
                lead = clean[line:join[0]] if not clean[line:join[0]].strip() else ''
                declare = (declaration_end, declaration_end, f'{indent}{kind}{stars}{copy};\n')
                insert = (join[1], join[1], f'\n{lead}{copy} = {local};')
                everything = [(a, b, copy) for a, b in rest]
                members = [(a, b, copy) for a, b in rest if re.match(r'\s*->', clean[b:b + 4])]
                out.append((FAMILY, edit(source, everything + [declare, insert])))
                if members and len(members) != len(rest):
                    out.append((DEREF_FAMILY, edit(source, members + [declare, insert])))
                drops = _drops(clean, part, [(join[1], block_end)], local)
                if drops:
                    # the dropped argument is the original local: the other later uses are renamed, that one goes
                    kept = [e for e in everything if not any(x[0] <= e[0] and e[1] <= x[1] for x in drops)]
                    out.append((DROP_FAMILY, edit(source, drops + kept + [declare, insert])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 50}  # the registry: no caller wiring (registry.py)
