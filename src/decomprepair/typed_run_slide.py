"""One statement of a run moved, where it or one it passes is on a typed pointer's member or steps a local.

`statement_slide` and `table_read_statement_slide` read `M2C_FIELD` cells and record casts. A source typed by hand or by
the app (`Ent *self` with `self->unk76 = 0;`) has neither, so none of its statements could move; nor could `n++;` or a
chain (`self->vx = self->vy = 0;`) be moved or passed. Two moves finished an 88-instruction N64 entity placer (SN GCC
2.8.1, `-G0 -mips3 -O2 -mfp64`), found by hand after both families offered nothing: `self->type = Table[self->slot];`
four statements up, above a byte store, a chain of halfword stores and two word clears (700 -> 60), and the loop's
`tries++;` below the three statements that follow it, the last a call (60 -> 0).

typed_member_slide
    One child per statement and distance (up to `REACH`), shortest first, at most `LIMIT`. A member of a declared struct
    pointer is compared by its byte interval; cells of two different pointers clash when their offsets overlap (they may
    be the same record). A chain writes every one of its targets. Only a local no call can reach passes a call. Moves
    the older two families can already read are left to them.

That a store through a pointer does not reach a table the function only reads is a hypothesis, as every reorder is; the
exact judge decides.
"""
import re

from .field_offsets import Types, _declarations
from .integer_repair_support import IDENT, view
from .statement_slide import CALL, CELL_KINDS, _effects, _locals, _record_cells, _runs
from .table_read_statement_slide import _statement_effects, _tables

FAMILY = 'typed_member_slide'
FAMILIES = (FAMILY,)
LIMIT = 60
REACH = 4
_MEMBER = re.compile(rf'(?<![\w.>)\]&])(?P<base>{IDENT})\s*->\s*(?P<member>{IDENT})(?!\w)(?!\s*(?:\.|\[|->|\())')
_STEP = re.compile(rf'\s*(?:(?:\+\+|--)\s*(?P<before>{IDENT})|(?P<after>{IDENT})\s*(?:\+\+|--))\s*;?\s*')
_ASSIGN = re.compile(r'(?<![=!<>+\-*/&|^%])=(?!=)')
_JUMP = re.compile(r'\s*(?:return|break|continue|goto)\b')


def _typed(text, pointers):
    """`text` with each scalar member of a declared struct pointer written as its `M2C_FIELD` cell."""
    def cell(found):
        record = pointers.get(found['base'])
        member = record and next((m for m in record.members if m.name == found['member']), None)
        if not member or member.dims or member.size not in CELL_KINDS:
            return found[0]
        return f'M2C_FIELD({found["base"]}, {CELL_KINDS[member.size]} *, {member.offset})'
    return _MEMBER.sub(cell, text)


def _read(text, tables):
    """(writes, reads) of one statement, or None. A step is a write and a read of its local; a chain writes each target."""
    step = _STEP.fullmatch(text)
    if step:
        key = {('v', step['before'] or step['after'])}
        return key, key
    signs = [found.start() for found in _ASSIGN.finditer(text.rstrip().rstrip(';'))]
    if len(signs) < 2:
        found = _statement_effects(text, tables) if tables else _effects(text)
        return found and (found[0], found[1])
    starts = [0] + [sign + 1 for sign in signs[:-1]]
    value = text.rstrip().rstrip(';')[signs[-1] + 1:]
    writes, reads = set(), set()
    for start, sign in zip(starts, signs):
        one = _read(f'{text[start:sign].strip()} = {value.strip()};', tables)
        if not one:
            return None
        writes |= one[0]
        reads |= one[1]
    return writes, reads


def _meet(first, second):
    for x in first:
        for y in second:
            if x[0] == y[0] == 'v' and x[1] == y[1]:
                return True
            if x[0] == y[0] == 'f' and x[2] < y[3] and y[2] < x[3]:
                return True
            if {x[0], y[0]} == {'v', 'f'}:
                cell, plain = (x, y) if x[0] == 'f' else (y, x)
                if cell[1].startswith('__global_') and (cell[1] == '__global_' + plain[1]):
                    return True
    return False


def _alone(effects, text, safe):
    """The names of a statement that only works on locals no call or store can reach, else nothing."""
    if not effects or any(key[0] != 'v' for key in effects[0] | effects[1]):
        return set()
    names = {key[1] for key in effects[0] | effects[1]}
    return names if names <= safe and not CALL.search(text) else set()


def _commute(moved, other, moved_text, other_text, safe):
    if moved and other:
        return not (_meet(moved[0], other[0] | other[1]) or _meet(other[0], moved[1]))
    # such a local passes any statement that does not name it, a call or a compound store included
    for effects, text, rest in ((moved, moved_text, other_text), (other, other_text, moved_text)):
        names = _alone(effects, text, safe)
        if names and not _JUMP.match(rest) and not names & set(re.findall(rf'\b{IDENT}\b', rest)):
            return True
    return False


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    types = Types(source, header)
    pointers = {var: record for var, (record, pointer, array) in
                _declarations((header or '') + '\n' + source, types).items() if pointer and not array}
    # the function's own declarations win over a same name declared elsewhere in the file or the header
    own = _declarations(part.source[part.clean.rfind('\n', 0, part.opening - 1) + 1:part.end], types)
    pointers.update({var: record for var, (record, pointer, array) in own.items() if pointer and not array})
    tables = _tables(source, header, part.clean[part.opening:part.end])
    safe = _locals(part)
    found = []
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end), minimum=2):
        texts = [part.clean[s:e] for s, e in run]
        typed = [_typed(_record_cells(text, types), pointers) for text in texts]
        effects = [_read(text, tables) for text in typed]
        # what only this family reads: a typed member, a step, a chain
        new = [typed[k] != _record_cells(text, types) or bool(_STEP.fullmatch(text))
               or len(_ASSIGN.findall(text.rstrip(';'))) > 1 for k, text in enumerate(texts)]
        for index in range(len(texts)):
            for step in range(1, REACH + 1):
                for sign in (1, -1):
                    target = index + sign * step
                    if not 0 <= target < len(texts):
                        continue
                    low, high = sorted((index, target))
                    passed = [k for k in range(low, high + 1) if k != index]
                    if not (new[index] or any(new[k] for k in passed)):
                        continue
                    if not all(_commute(effects[index], effects[k], texts[index], texts[k], safe) for k in passed):
                        continue
                    order = list(range(len(texts)))
                    order.insert(target, order.pop(index))
                    child = source[:run[0][0]]
                    for k, was in enumerate(order):
                        gap = source[run[k - 1][1]:run[k][0]] if k else ''
                        child += gap + source[run[was][0]:run[was][1]]
                    found.append((step, child + source[run[-1][1]:]))
    result = []
    for _, child in sorted(found, key=lambda item: item[0]):
        if child != source and child not in result:
            result.append(child)
    return [(FAMILY, child) for child in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
