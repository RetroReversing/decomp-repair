"""Snapshot the invariant delta in a measured bounded field loop."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lw \$v0, (?P<guard>{NUM})\(\$a0\)\nlw \$t1, (?P<delta>{NUM})\(\$a0\)\n'
    rf'bnez \$v0, [^\n]+\naddiu \$t0, \$zero, -1'
)
LOOP = re.compile(
    rf'lw \$v0, (?P<field>{NUM})\(\$a2\)\nsubu \$v0, \$v0, \$t1\n'
    rf'sw \$v0, (?P=field)\(\$a2\)'
)
CANDIDATE = re.compile(
    rf'lw \$v0, (?P<field>{NUM})\(\$a2\)\nlw \$v1, (?P<delta>{NUM})\(\$a0\)\n'
    rf'subu \$v0, \$v0, \$v1\nsw \$v0, (?P=field)\(\$a2\)'
)
FIELD = r'M2C_FIELD\s*\(\s*{obj}\s*,\s*{kind}\s*\*\s*,\s*{offset}\s*\)'


def variants(source, name, header, rows):
    target, candidate = ('\n'.join(' '.join(row[side].split()) for row in rows if row[side]) for side in (1, 2))
    t, loop, c = TARGET.search(target), LOOP.search(target), CANDIDATE.search(candidate)
    if not t or not loop or not c or int(t['delta'], 0) != int(c['delta'], 0):
        return []
    if int(loop['field'], 0) != int(c['field'], 0):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    # Match the whole body: no hidden writes, calls, aliases or alternate exits can
    # invalidate the value while the cursor walks the bounded array.
    f = lambda obj, kind, offset: FIELD.format(obj=obj, kind=kind, offset=offset)  # noqa: E731
    pattern = re.compile(
        rf'\s*u32\s+(?P<temp>{IDENT})\s*;\s*u32\s+(?P<index>{IDENT})\s*;\s*'
        rf'u32\s+(?P<minimum>{IDENT})\s*;\s*void\s*\*\s*(?P<cursor>{IDENT})\s*;\s*'
        rf'(?P<init>(?P=minimum)\s*=\s*-1U\s*;)\s*'
        rf'if\s*\(\s*{f("(?P<owner>" + IDENT + ")", "u32", "(?P<guard>" + NUM + ")")}\s*==\s*0\s*\)\s*'
        rf'{{\s*return\s+0\s*;\s*}}\s*(?P=index)\s*=\s*0\s*;\s*(?P=cursor)\s*=\s*(?P=owner)\s*;\s*'
        rf'(?P<label>{IDENT})\s*:\s*{{\s*if\s*\(\s*\(\s*\(\s*u32\s*\)\s*'
        rf'{f("(?P=owner)", "u32", "(?P=guard)")}\s*>>\s*(?P=index)\s*\)\s*&\s*1\s*\)\s*{{\s*'
        rf'if\s*\(\s*{f("(?P=owner)", "s32", "(?P<clear>" + NUM + ")")}\s*!=\s*0\s*\)\s*{{\s*'
        rf'{f("(?P=cursor)", "u32", "(?P<field>" + NUM + ")")}\s*=\s*\(\s*u32\s*\)\s*\(\s*'
        rf'{f("(?P=cursor)", "u32", "(?P=field)")}\s*-\s*'
        rf'(?P<read>{f("(?P=owner)", "s32", "(?P<delta>" + NUM + ")")})\s*\)\s*;\s*}}\s*'
        rf'(?P=temp)\s*=\s*{f("(?P=cursor)", "u32", "(?P=field)")}\s*;\s*'
        rf'if\s*\(\s*(?P=temp)\s*<\s*(?P=minimum)\s*\)\s*{{\s*(?P=minimum)\s*=\s*(?P=temp)\s*;\s*}}\s*}}\s*'
        rf'(?P=index)\s*\+=\s*1\s*;\s*(?P=cursor)\s*\+=\s*4\s*;\s*}}\s*'
        rf'if\s*\(\s*(?P=index)\s*<\s*(?P<count>{NUM})U\s*\)\s*goto\s+(?P=label)\s*;\s*'
        rf'{f("(?P=owner)", "s32", "(?P=clear)")}\s*=\s*0\s*;\s*'
        rf'\*\s*(?P<out>{IDENT})\s*=\s*(?P=minimum)\s*;\s*return\s+1\s*;\s*'
    )
    m = pattern.fullmatch(part.body)
    if not m:
        return []
    if any(int(m[k], 0) != int(v, 0) for k, v in [('guard', t['guard']), ('delta', t['delta']), ('field', loop['field'])]):
        return []
    count, field, delta = (int(m[k], 0) for k in ('count', 'field', 'delta'))
    if not 1 <= count <= 32 or not (delta + 4 <= field or delta >= field + 4 * count):
        return []
    if len({m[k] for k in ('temp', 'index', 'minimum', 'cursor', 'owner', 'out')}) != 6:
        return []
    signature = part.clean[:part.opening]
    if not re.search(rf'\b{re.escape(name)}\s*\(\s*void\s*\*\s*{m["owner"]}\s*,\s*u32\s*\*\s*{m["out"]}\s*\)\s*$', signature):
        return []
    # A macro for a local or parameter could make the textual body misleading.
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection(m[k] for k in ('temp', 'index', 'minimum', 'cursor', 'owner', 'out')):
        return []
    if re.search(r'\b__repair_delta_snapshot\b', part.clean + '\n' + header):
        return []
    # The measured target reads before the early guard, not just before the loop.
    start = part.opening + 1
    return [('measured_loop_delta_snapshot', edit(source, [
        (start, start, '\n    s32 __repair_delta_snapshot;'),
        (start + m.start('init'), start + m.start('init'), f'__repair_delta_snapshot = {m["read"]};\n    '),
        (start + m.start('read'), start + m.end('read'), '__repair_delta_snapshot'),
    ]))]
