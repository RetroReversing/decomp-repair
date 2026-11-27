"""The shifted operands of one statement, each computed into a local and shifted there before the statement.

A fixed-point length is usually drafted as `return f(((u32)(x * x) >> 12) + ((u32)(y * y) >> 12));`: each square and its
shift are unnamed temporaries. The original named them and shifted each in place:

    u32 a = x * x;
    u32 b = y * y;
    a >>= 12;
    b >>= 12;
    return f(a + b);

On a 39-instruction N64 vector length (SN64 GCC 2.8.1, `-G0 -mips3 -mgp32 -mfp32 -O2`) the inline form left four
register rows (the first `mflo` took `$a3` where the game's took `$v0`) and was 20; the form above is exact. Naming the
products without shifting them in place stayed 20. `last_use_shift_in_place` writes the in-place shift only once the
locals exist; this makes them and shifts them in one child, which no single earlier step reaches.

Two children per statement: both locals computed and then both shifted, and each computed and shifted before the next.
Only operands built from integer parameters and locals (never a global, a pointer read or a call), so computing them
before the statement reads the same values. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import INTEGER, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'shifted_operand_locals'
FAMILIES = (FAMILY,)
LIMIT = 4

_TYPE = rf'(?:{INTEGER}|unsigned|signed|long)'
_CAST = re.compile(r'\(\s*(?P<type>u32|s32|unsigned\s+int|unsigned|int)\s*\)\s*(?=\()')
_SHIFT = re.compile(r'\s*>>\s*(?P<amount>0[xX][0-9a-fA-F]+|[0-9]+)\s*(?=\))')
_STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<text>[^;{}\s][^;{}]*;)')
_DECLARED = re.compile(rf'\b(?P<type>{_TYPE})\s+(?P<name>[A-Za-z_]\w*)\s*(?=[;=,)])')
_ARITHMETIC = re.compile(r'(?:[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|[0-9]+|<<|>>|[-+*&|^()~\s])+')


def _integers(part):
    """{name: type} of the integer parameters and locals whose address is never taken."""
    head = part.clean[part.clean.rfind('\n', 0, part.clean.rfind('(', 0, part.opening)) + 1:part.opening]
    found, seen = {}, set()
    for text in (head, part.body):
        for hit in _DECLARED.finditer(text):
            name = hit['name']
            if name in seen:
                found.pop(name, None)  # declared twice: which one the statement means is not read here
            elif not _address_taken(part.body, name):
                found[name] = ' '.join(hit['type'].split())
            seen.add(name)
    return found


def _operands(text, integers):
    """[(start, stop, expression, type, amount)] of the `((T)(E) >> K)` and `((E) >> K)` operands in a statement."""
    out, taken = [], 0
    for opening in (hit.start() for hit in re.finditer(r'\(', text)):
        start = opening + 1
        start += len(text[start:]) - len(text[start:].lstrip())
        if start < taken:
            continue
        cast = _CAST.match(text, start)
        at = cast.end() if cast else start
        if text[at:at + 1] != '(':
            continue
        shut = close(text, at)
        shift = _SHIFT.match(text, shut) if shut is not None else None
        if not shift:
            continue
        expression = text[at + 1:shut - 1].strip()
        names = [word for word in re.findall(r'\b[A-Za-z_]\w*', expression) if not re.fullmatch(_TYPE, word)]
        if (not _ARITHMETIC.fullmatch(expression) or not names or any(word not in integers for word in names)
                or not re.search(r'[-+*&|^<>~]', expression)):
            continue
        if cast:
            kind = 'u32' if cast['type'].startswith('u') else 's32'
        else:
            kind = 'u32' if any(integers[word] in ('u32', 'unsigned', 'unsigned int') for word in names) else 's32'
        out.append((start, shift.end(), expression, kind, shift['amount']))
        taken = shift.end()
    return out


def _plain(text):
    """Whether the statement writes nothing before its operands could be read: one assignment at most, no steps."""
    if re.match(rf'(?:if|else|while|for|do|switch|case|default|goto|break|continue|{_TYPE}|float|f32|struct|union)\b', text):
        return False
    if re.match(r'[A-Za-z_]\w*\s*:(?!:)', text) or '++' in text or '--' in text or text.count('(') != text.count(')'):
        return False
    return len(re.findall(r'(?<![=!<>])=(?!=)|<<=|>>=', text)) <= 1


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body) or '__repair_shifted' in source:
        return []
    integers = _integers(part)
    out, done = [], 0
    for hit in _STATEMENT.finditer(part.clean, part.opening + 1, part.end - 1):
        text = hit['text']
        if done == LIMIT or not _plain(text):
            continue
        operands = _operands(text, integers)
        if len(operands) < 2:
            continue
        done += 1
        names = [f'__repair_shifted_{index}' for index in range(len(operands))]
        start = hit.start('text')
        statement = source[start:hit.end('text')]
        for index in range(len(operands) - 1, -1, -1):
            statement = statement[:operands[index][0]] + names[index] + statement[operands[index][1]:]
        indent = hit['indent']
        inner = indent + '    '
        pairs = list(zip(names, operands))
        together = ([f'{kind} {local} = {expression};' for local, (_, _, expression, kind, _) in pairs]
                    + [f'{local} >>= {amount};' for local, (_, _, _, _, amount) in pairs])
        first, (_, _, expression, kind, amount) = pairs[0]
        in_turn = [f'{kind} {first} = {expression};']
        in_turn += [f'{kind_} {local};' for local, (_, _, _, kind_, _) in pairs[1:]]
        in_turn.append(f'{first} >>= {amount};')
        for local, (_, _, expression, _, amount) in pairs[1:]:
            in_turn += [f'{local} = {expression};', f'{local} >>= {amount};']
        for lines in (together, in_turn):
            block = '{\n' + ''.join(f'{inner}{line}\n' for line in [*lines, statement]) + indent + '}'
            out.append((FAMILY, edit(source, [(start, hit.end('text'), block)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
