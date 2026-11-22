"""Distribute a shared byte store into measured independent branch stores."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'addiu \$v0, \$zero, (?P<same>{NUM})\naddiu \$v1, \$zero, (?P<middle>{NUM})\n'
    rf'sb \$v0, (?P<first>{NUM})\(\$a0\)\nsb \$v0, (?P<third>{NUM})\(\$a0\)\n'
    rf'addiu \$v0, \$zero, (?P<last>{NUM})\nj [^\n]+\nsb \$v1, (?P<second>{NUM})\(\$a0\)'
)
CANDIDATE = re.compile(
    rf'addiu \$v0, \$zero, (?P<same>{NUM})\nsb \$v0, (?P<first>{NUM})\(\$a0\)\n'
    rf'sb \$v0, (?P<third>{NUM})\(\$a0\)\naddiu \$v0, \$zero, (?P<middle>{NUM})\n'
    rf'j [^\n]+\nsb \$v0, (?P<second>{NUM})\(\$a0\)'
)
STORE = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>[su]8)\s*\*\s*,\s*'
                   rf'(?P<offset>{NUM})\s*\)\s*=\s*(?P<value>{NUM})\s*;')
BRANCH = re.compile(r'if\s*\([^{};]+\)\s*\{(?P<yes>[^{}]*)\}\s*else\s*\{(?P<no>[^{}]*)\}\s*'
                    r'(?P<after>M2C_FIELD\([^;]+\)\s*=\s*[^;]+;)')


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or any(int(t[k], 0) != int(c[k], 0) for k in ('same', 'middle', 'first', 'second', 'third')):
        return []
    offsets = [int(t[k], 0) for k in ('first', 'second', 'third')]
    if offsets != list(range(offsets[0], offsets[0] + 3)):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    results = []
    for branch in BRANCH.finditer(part.body):
        arms = []
        for key in ('yes', 'no'):
            text = branch[key]
            stores = list(STORE.finditer(text))
            if len(stores) != 3 or STORE.sub('', text).strip():
                break
            arms.append(stores)
        if len(arms) != 2:
            continue
        after = STORE.fullmatch(branch['after'])
        if not after or any(m['base'] != after['base'] for arm in arms for m in arm):
            continue
        yes, no = arms
        if ([int(m['offset'], 0) for m in yes] != [offsets[0], offsets[2], offsets[1]]
                or [int(m['offset'], 0) for m in no] != offsets
                or int(after['offset'], 0) != offsets[0] + 3
                or int(after['value'], 0) != int(t['last'], 0)
                or [int(m['value'], 0) for m in yes] != [int(t['same'], 0), int(t['same'], 0), int(t['middle'], 0)]):
            continue
        if re.search(rf'(?m)^\s*#\s*define\s+{re.escape(after["base"])}\b', source + '\n' + header):
            continue
        original = source[part.opening + 1 + branch.start():part.opening + 1 + branch.end()]
        if '/*' in original or '//' in original or '#' in original:
            continue
        begin = part.opening + 1 + branch.start()
        yes_start = begin + branch.start('yes') - branch.start()
        no_end = begin + branch.end('no') - branch.start()
        # The stores address four distinct bytes and have constant values. Keep
        # the guarded final store after each branch, before the shared code.
        ordered = '\n                '.join(m[0] for m in (yes[0], yes[2], yes[1]))
        replacement_yes = '\n                ' + ordered + '\n                ' + after[0] + '\n            '
        replacement_no = branch['no'].rstrip() + '\n                ' + after[0] + '\n            '
        edits = [(yes_start, yes_start + len(branch['yes']), replacement_yes),
                 (begin + branch.start('no') - branch.start(), no_end, replacement_no),
                 (begin + branch.start('after') - branch.start(), begin + branch.end('after') - branch.start(), '')]
        results.append(('measured_branch_byte_stores', edit(source, edits)))
    return results[:1]
