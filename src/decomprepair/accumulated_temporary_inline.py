"""A value m2c built up in a local over several statements, written whole at each place it is read.

m2c names a product term the compiler computed once and kept, and writes it ahead of the calls it was computed
after:

    t = (u32) (raw & 0xFFFF) >> 6; t += 0x733;      speed = f(angle) * ((raw >> 6) + 0x733);
    x = f(angle) * t;                         ->     y = g(angle) * ((raw >> 6) + 0x733);
    y = g(angle) * t;

The game wrote the expression where it is read. The operands are evaluated left to right, so the call comes first and
the arithmetic after it, and the compiler's value reuse keeps the one result for the second read. A local set ahead of
the calls computes it before the first call instead. On a 102-instruction N64 object update (SN64 GCC, `-O2 -mips3`)
that placement was three instructions in the wrong place; with the other two steps of the chain in, this one took
the score from 120 to 0. The left-to-right reading is a hypothesis that the measurement agrees with, and the judge
decides each child. `single_use_inline` does not offer it: the `+=` assigns the local again after its first set.

The child (`accumulated_temporary_inline`, one per qualifying local, bounded) removes `V = E;` and the `V op= K;`
statements that follow it and writes `((T) (expression))` for every later read of `V`, when:
- `V` is a plain integer local whose every mention is the declaration, those statements, or a read after them inside
  the same block;
- `E` and each `K` read only literals and integer locals or parameters (no call, memory read, address, increment or
  assignment) and none of those is assigned or address-taken from there to the end of the block;
- no label stands between the statements and the last read, so no jump can arrive there without them."""
import re

from .integer_repair_support import DECL, IDENT, INTEGER, edit, locals_for, refs, view
from .pattern_repairs import close

FAMILY = 'accumulated_temporary_inline'
FAMILIES = (FAMILY,)
LIMIT = 6

_NARROW = re.compile(r'(?:unsigned\s+|signed\s+)?(?:char|short(?:\s+int)?)|[su](?:8|16)')
_TYPE_WORDS = {'u8', 's8', 'u16', 's16', 'u32', 's32', 'int', 'short', 'char', 'unsigned', 'signed', 'long'}
_PURE = re.compile(r'[\w\s()+\-*/%&|^~<>!]+\Z')
_STATEMENT = rf'[ \t\n]*({IDENT})\s*(<<|>>|[-+*/%&|^])?=(?!=)([^;{{}}=]+);'


def _plain(expression, operands):
    """Arithmetic over literals and the given locals: no call, member, dereference, address or assignment."""
    if not _PURE.match(expression) or re.search(r'\+\+|--|->', expression):
        return False
    # a `*` or `&` with no value before it is a dereference or an address
    if re.search(r'(?:^|[(+\-*/%&|^~!<>])\s*(?:\*|&(?!&))(?!\))', expression.replace('&&', ' ').replace('<<', ' << ')):
        return False
    if re.search(r'\b(?!(?:' + '|'.join(_TYPE_WORDS) + r')\b)[A-Za-z_]\w*\s*\(', expression):
        return False
    names = set(re.findall(r'(?<![\w])[A-Za-z_]\w*', expression))
    return names <= operands | _TYPE_WORDS


def _assigned(name, text):
    return bool(re.search(rf'(?<![\w.]){name}\s*(?:<<|>>|[-+*/%&|^])?=(?!=)|\b{name}\s*(?:\+\+|--)|(?:\+\+|--)\s*{name}\b'
                          rf'|(?<![&\w)\]]\s)(?<![&\w)\]])&\s*{name}\b', text))


def _block_end(part, position):
    """The `}` closing the block that holds `position` (the function's own when it is at the top level)."""
    stack = [part.opening]
    for hit in re.finditer(r'[{}]', part.clean[part.opening + 1:position]):
        if hit[0] == '{':
            stack.append(part.opening + 1 + hit.start())
        elif len(stack) > 1:
            stack.pop()
    end = close(part.clean, stack[-1], '{', '}')
    return end - 1 if end else None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    declared = {decl['name']: decl for decl in locals_for(part)}
    header = clean[max(clean.rfind(';', 0, part.opening), clean.rfind('}', 0, part.opening)) + 1:part.opening]
    parameters = {hit[1] for hit in re.finditer(rf'\b{INTEGER}\s+({IDENT})\s*(?=[,)])', header)
                  if not re.search(rf'&\s*{hit[1]}\b', part.body)}
    operands = set(declared) | parameters
    result = []
    for local, decl in declared.items():
        mentions = refs(part, decl)
        if len(mentions) < 3:
            continue
        first = mentions[0].start()
        if clean[part.opening:first].rstrip()[-1:] not in (';', '{', '}'):
            continue
        steps, position = [], first
        while True:
            found = re.compile(_STATEMENT).match(clean, position)
            if not found or found[1] != local or bool(found[2]) != bool(steps):
                break
            steps.append(found)
            position = found.end()
        if len(steps) < 2:
            continue
        block_end = _block_end(part, first)
        reads = [hit for hit in mentions if hit.start() >= position]
        if block_end is None or not reads or reads[-1].start() >= block_end:
            continue
        if sum(hit.start() < position for hit in mentions) != len(steps):
            continue  # a step reads the local on its right side
        if _assigned(local, clean[position:block_end]) or re.search(rf'(?<![?\w]){IDENT}\s*:(?!:)\s*(?!\s*\d)',
                                                                  re.sub(r'\?[^;]*:', '', clean[position:reads[-1].start()])):
            continue
        values = [source[step.start(3):step.end(3)].strip() for step in steps]
        if not all(_plain(clean[step.start(3):step.end(3)].strip(), operands - {local}) for step in steps):
            continue
        used = {word for value in values for word in re.findall(r'(?<!\w)[A-Za-z_]\w*', value)} - _TYPE_WORDS
        if any(_assigned(word, clean[position:block_end]) for word in used):
            continue
        kind = ' '.join(decl['type'].split())
        expression = values[0]
        for step, value in zip(steps[1:], values[1:]):
            # shifting right, dividing and a narrow local read the value as the local holds it, not as it was computed
            if step[2] in ('>>', '/', '%') or _NARROW.fullmatch(kind):
                expression = f'({kind}) ({expression})'
            if not re.fullmatch(r'\w+', value):
                value = f'({value})'
            expression = f'({expression}) {step[2]} {value}'
        spelled = f'(({kind}) ({expression}))'
        start = steps[0].start(1)
        while start > 0 and source[start - 1] in ' \t':
            start -= 1
        end = position
        if (start == 0 or source[start - 1] == '\n') and source[end:end + 1] == '\n':
            end += 1
        edits = [(start, end, '')] + [(hit.start(), hit.end(), spelled) for hit in reads]
        line = DECL.match(source, decl.start())
        if line:
            begin = source.rfind('\n', 0, line.start()) + 1
            if not source[begin:line.start()].strip() and source[line.end():line.end() + 1] == '\n':
                edits.append((begin, line.end() + 1, ''))
        result.append((FAMILY, edit(source, edits)))
        if len(result) == LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
