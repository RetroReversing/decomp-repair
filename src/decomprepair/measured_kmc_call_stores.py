"""Select measured KMC candidates around published fields and call delay slots."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_PUBLISH = re.compile(
    r'lw \$a0, (?P<field>\d+)\(\$s0\)\n'
    rf'lui \$at, %hi\((?P<dest>{IDENT})\)\nsw \$s0, %lo\((?P=dest)\)\(\$at\)\n'
    rf'jal (?P<call>{IDENT})\nnop\nmove \$v0, \$s0'
)
_PUBLISH_SOURCE = re.compile(
    rf'\s*(?P<store>M2C_FIELD\(&(?P<owner>{IDENT}), void \*\*, (?P<offset>{NUMBER})\) = (?P<input>{IDENT});)'
    rf'\s*(?P<call>{IDENT})\((?P<load>M2C_FIELD\((?P=input), s32 \*, (?P<field>{NUMBER})\))\);'
    r'\s*return (?P=input);\s*'
)
_YIELD = re.compile(
    rf'lui \$v1, %hi\((?P<owner>{IDENT})\)\nlw \$v1, %lo\((?P=owner)\)\(\$v1\)\n'
    rf'lui \$a0, %hi\((?P<queue>{IDENT})\)\naddiu \$a0, \$a0, %lo\((?P=queue)\)\n'
    r'addiu \$a1, \$zero, (?P<value>\d+)\nmove \$s0, \$v0\n'
    rf'jal (?P<call>{IDENT})\nsh \$a1, (?P<offset>\d+)\(\$v1\)\njal (?P<restore>{IDENT})\nmove \$a0, \$s0'
)
_YIELD_SOURCE = re.compile(
    rf'\s*s32 (?P<saved>{IDENT});\s*(?P=saved) = (?P<save>{IDENT})\(\);\s*'
    rf'(?P<store>M2C_FIELD\((?P<owner>{IDENT}), s16 \*, (?P<offset>{NUMBER})\) = (?P<value>{NUMBER});)\s*'
    rf'(?P<call>{IDENT})\(&(?P<queue>{IDENT}), (?P<valuearg>{NUMBER})\);\s*(?P<restore>{IDENT})\((?P=saved)\);\s*'
)


def variants(source, name, header, rows, resolve=None):
    if len(rows) not in (14, 19):
        return []
    differences = [(left, right) for mark, left, right in rows if mark != ' ']
    if len(differences) != 2:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if resolve and (hit := _PUBLISH.search(target)):
        load = next(line for line in hit[0].splitlines() if line.startswith('lw '))
        if [normalized_integer_lines(pair) for pair in differences] != [(load, ''), ('nop', load)]:
            return []
        family, rewrite = 'measured_load_before_publishing_pointer', _publish_load
    elif hit := _YIELD.search(target):
        store = f'sh $a1, {hit["offset"]}($v1)'
        if [normalized_integer_lines(pair) for pair in differences] != [
            ('', store), (store, f'addiu $a1, $zero, {hit["value"]}'),
        ]:
            return []
        family, rewrite = 'measured_staged_call_halfword', _stage_halfword
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    fixed = rewrite(part, name, header, resolve, hit)
    return [(family, fixed)] if fixed else []


def _publish_load(part, name, header, resolve, target):
    local = '__repair_publish_field'
    if local in part.source + header:
        return None
    source = _PUBLISH_SOURCE.fullmatch(part.body)
    signature = re.search(rf'\bvoid\s*\*\s*{re.escape(name)}\(void \*({IDENT})\)\s*$', part.clean[:part.opening])
    if not source or not signature or source['input'] != signature[1] or source['call'] != target['call']:
        return None
    addr = resolve(source['owner'])
    if addr is None or addr + integer(source['offset']) != resolve(target['dest']) or integer(source['field']) != int(target['field']):
        return None
    start = part.opening + 1
    return edit(part.source, [
        (start, start, f'\n    s32 {local} = {source["load"]};'),
        (start + source.start('load'), start + source.end('load'), local),
    ])


def _stage_halfword(part, name, header, _resolve, target):
    local = '__repair_call_halfword'
    source = _YIELD_SOURCE.fullmatch(part.body)
    if not source or local in part.source + header or not re.search(
        rf'\bvoid\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening]
    ):
        return None
    if any(source[key] != target[key] for key in ('owner', 'call', 'queue', 'restore')):
        return None
    if (integer(source['value']) != int(target['value']) or integer(source['valuearg']) != int(target['value'])
            or integer(source['offset']) != int(target['offset'])):
        return None
    start = part.opening + 1
    return edit(part.source, [
        (start, start, f'\n    s32 {local};'),
        (start + source.start('store'), start + source.start('store'), f'{local} = {source["value"]};\n    '),
        (start + source.start('value'), start + source.end('value'), local),
    ])
