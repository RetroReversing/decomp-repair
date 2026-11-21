"""Recover indexed field stores when an m2c record cursor runs beside a counter."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines
from .pattern_repairs import close

REG = r'\$\w+'
SAVED = r'\$s[0-7]'
LATCH = re.compile(
    rf'(?m)^addiu (?P<count>{SAVED}), (?P=count), (?:1|0x1)\n'
    rf'sltiu (?P<flag>{REG}), (?P=count), (?P<limit>{NUMBER})\n'
    rf'bnez (?P=flag), (?P<label>\.L\w+)\naddiu (?P<cursor>{SAVED}), (?P=cursor), (?:4|0x4)$'
)


def _evidence(asm):
    if 'sltiu' not in asm or 'bnez' not in asm:
        return None
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm))
    lines = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', lines)
    for tail in LATCH.finditer(lines):
        count, cursor = map(re.escape, (tail['count'], tail['cursor']))
        limit = integer(tail['limit'])
        if count == cursor or not 0 < limit <= 0x7FFF:
            continue
        label = re.search(rf'(?m)^{re.escape(tail["label"])}:$', lines[:tail.start()])
        if not label:
            continue
        prefix = lines[:label.start()]
        copied = list(re.finditer(rf'(?m)^move {cursor}, (?P<base>{SAVED})$', prefix))
        if len(copied) != 1 or not re.search(rf'(?m)^move {count}, \$zero$', prefix):
            continue
        base = re.escape(copied[0]['base'])
        if (base in (count, cursor) or re.search(rf'{cursor}\b', prefix[copied[0].end():])
                or not re.search(rf'(?m)^move {base}, \$a0$', prefix[:copied[0].start()])):
            continue
        body = lines[label.end():tail.start()]
        stores = [line for line in body.splitlines() if re.search(rf'{cursor}\b', line)]
        offsets = [re.fullmatch(rf'sw {REG}, ({NUMBER})\({cursor}\)', line) for line in stores]
        read = re.search(
            rf'(?m)^lw (?P<table>{REG}), (?:0|0x0)?\({base}\)\nsll (?P<index>{REG}), {count}, (?:2|0x2)\n'
            rf'addu (?P=index), (?P=index), (?P=table)\nlw {REG}, (?:0|0x0)?\((?P=index)\)$', body)
        if read and len(offsets) >= 2 and all(offsets):
            return limit, [integer(match[1]) for match in offsets]
    return None


def applies(asm):
    return _evidence(asm) is not None


def rewrite(source, name, asm, header=''):
    """Derive word offsets from the counter and preserve the remaining loop body."""
    if 'M2C_FIELD' not in source or not (target := _evidence(asm)):
        return None
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto|continue)\b', part.body):
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*(?P<base>{IDENT}), void \*{IDENT}\)\s*$',
                          part.clean[:part.opening])
    loops = list(re.finditer(r'\bdo\s*\{', part.body))
    if not signature or len(loops) != 1:
        return None
    opening = part.opening + loops[0].end()
    end = close(part.clean, opening, '{', '}')
    if not end:
        return None
    tail = re.match(rf'\s*while \((?P<count>{IDENT}) < (?P<limit>{NUMBER})\);', part.clean[end:part.end])
    if not tail or integer(tail['limit']) != target[0]:
        return None
    base, count = signature['base'], tail['count']
    growth = re.search(rf'(?m)^[ \t]*{count} \+= 1;\n(?P<step>[ \t]*(?P<cursor>{IDENT}) \+= 4;\n)\s*\Z',
                       part.clean[opening + 1:end - 1])
    if not growth or growth['cursor'] in (base, count):
        return None
    cursor = growth['cursor']
    prefix = part.clean[part.opening + 1:opening]
    setup = re.search(rf'(?m)^[ \t]*{count} = 0;\n(?P<init>[ \t]*{cursor} = {base};\n)', prefix)
    declaration = re.search(rf'(?m)^[ \t]*void \*{cursor};\n', prefix)
    if not setup or not declaration or not re.search(rf'\bu32 {count};', prefix):
        return None
    body_start = opening + 1
    body = part.clean[body_start:body_start + growth.start()]
    fields = list(re.finditer(rf'\bM2C_FIELD\({cursor}, s32 \*, ({NUMBER})\)(?= =)', body))
    if [integer(match[1]) for match in fields] != target[1]:
        return None
    if len(re.findall(rf'\b{cursor}\b', part.body)) != len(fields) + 3:
        return None
    changed = rf'(?:&\s*(?:\(\s*)*|\+\+\s*|--\s*)\b(?:{base}|{count})\b|\b(?:{base}|{count})\s*(?:\+\+|--|(?:[+*/%&|^-]|<<|>>)?=(?!=))'
    if (re.search(changed, body) or re.search(changed, prefix[setup.end():])
            or re.search(rf'(?m)^\s*#\s*define\s+(?:{base}|{count}|{cursor})\b', source + '\n' + header)):
        return None
    start = part.opening + 1
    edits = [(start + declaration.start(), start + declaration.end(), ''),
             (start + setup.start('init'), start + setup.end('init'), ''),
             (body_start + growth.start('step'), body_start + growth.end('step'), '')]
    edits += [(body_start + match.start(), body_start + match.end(),
               f'M2C_FIELD({base}, s32 *, {count} * 4 + {match[1]})') for match in fields]
    # The indexed table read is already word-typed in compiled drafts.
    untyped = list(re.finditer(rf'(?<== )\*\(\({count} \* 4\) \+ M2C_FIELD\({base}, void \*\*, 0\)\)(?=;)', body))
    if len(untyped) > 1:
        return None
    if untyped:
        at = body_start + untyped[0].start() + 1
        edits.append((at, at, '(s32 *)'))
    return edit(source, edits)
