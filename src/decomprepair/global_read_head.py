"""A global read into a local, moved from deep in a run of stores to the head of that run.

m2c writes `t = G + 1;` where the target's `addiu` landed, which can be far below where the source read `G`: the
scheduler hoists the load and leaves the arithmetic with its use, so the draft's statement sits beside the arithmetic.
Where the read is in the source decides which constant is materialised before it and which register holds the value.
`statement_slide` moves a statement `statement_slide.REACH` places at most; this offers the two places at the head of
the run for a statement further down than that (before its first statement, and after it).

A 46-instruction N64 entity initialiser (SN GCC 2.8.1 `-G0 -mips3 -O2`): nine stores of constants through the
parameter, then `serial = sSerial + 1;`. At the head of the run the judge went 460 -> 60, and 60 -> 0 with the stores
written as members (`m2c_field_record_view`).

A child is offered only when the statement commutes with every statement it passes (`statement_slide.commutes`: no
call, no unknown pointer store, no shared local). A store through a pointer's field is taken not to change a scalar
global the code names, as `statement_slide` does; the judge decides.
"""
import re

from .field_offsets import Types
from .integer_repair_support import IDENT, view
from .statement_slide import REACH, _locals, _record_cells, _runs, commutes

FAMILY = 'global_read_head'
FAMILIES = (FAMILY,)
LIMIT = 12
HEADS = (0, 1)  # before the run's first statement, and after it
ASSIGN = re.compile(rf'\s*(?P<local>{IDENT})\s*=(?!=)\s*(?P<value>[^;]+?)\s*;\s*$', re.S)
# What a value may not hold: a call, a member, an element, an address, another assignment or a step.
UNSAFE = re.compile(r'[A-Za-z_]\w*\s*\(|->|\.[A-Za-z_]|\[|(?<!&)&(?!&)\s*[A-Za-z_]|\+\+|--|(?<![=!<>])=(?!=)')
# Names that are not variables: types in casts, keywords and the null macro.
NOT_GLOBAL = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 's64', 'u64', 'f32', 'f64', 'int', 'char', 'short', 'long', 'float',
              'double', 'unsigned', 'signed', 'void', 'const', 'volatile', 'struct', 'sizeof', 'NULL'}


def _own_names(part):
    """Every name the function declares: its parameters and locals, of any type."""
    signature = part.clean[:part.opening]
    head = signature[signature.rfind('(') + 1:signature.rfind(')')]
    names = {found[1] for piece in head.split(',') for found in [re.search(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*$', piece)]
             if found}
    body = part.clean[part.opening:part.end]
    names |= set(re.findall(rf'(?m)^[ \t]*(?!(?:return|goto|else)\b)(?:(?:register|static|const|volatile|unsigned|signed|'
                            rf'struct|union)[ \t]+)*{IDENT}(?:[ \t]*\*+[ \t]*|[ \t]+)({IDENT})[ \t]*(?:\[[^\]]*\])*[ \t]*[;=]',
                            body))
    return names


def _reads_global(value, own):
    if UNSAFE.search(value) or re.search(r'(?:^|[-+*/%|^<>=?:(,!~&])\s*\*', value):
        return False
    return any(ident not in own and ident not in NOT_GLOBAL
               for ident in re.findall(rf'(?<![\w.]){IDENT}\b', value))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    safe, own = _locals(part), _own_names(part)
    types = Types(source, header) if '->' in part.clean else None
    result = []
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end)):
        texts = [source[s:e] for s, e in run]
        read = [_record_cells(text, types) if types else text for text in texts]
        for index, text in enumerate(texts):
            found = ASSIGN.match(text)
            if not found or found['local'] not in safe or not _reads_global(found['value'], own):
                continue
            for target in HEADS:
                if index - target <= REACH or not all(commutes(read[index], read[k]) for k in range(target, index)):
                    continue
                order = list(range(len(texts)))
                order.insert(target, order.pop(index))
                child = source[:run[0][0]]
                for k, piece in enumerate(order):
                    gap = source[run[k - 1][1]:run[k][0]] if k else ''
                    child += gap + texts[piece]
                child += source[run[-1][1]:]
                if child not in result:
                    result.append(child)
    return [(FAMILY, child) for child in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
