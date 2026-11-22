"""Recover a masked lookup switch with shared table and fallback tails."""

import re

from . import if_tree_switch_repairs as tree
from .integer_repair_support import IDENT, NUMBER, integer, view
from .pattern_repairs import close

_PREFIX = re.compile(
    rf'\s*(?:(?:s32\s*\*?|u32)\s*{IDENT};\s*)+'
    rf'(?P<table_reg>{IDENT}) = (?P<unused>{IDENT});\s*'
    rf'(?P<index>{IDENT}) = (?P<arg>{IDENT}) & 0xFFF;\s*'
    rf'(?P<key>{IDENT}) = (?P=arg) & 0xF000;\s*(?=if\s*\()'
)
_FALLBACK = re.compile(
    rf'(?m)^\s*(?P<label>{IDENT}):\s*return (?P<name>{IDENT})\((?P<id>{NUMBER}), (?P<table>{IDENT})\);\s*$'
)
_SHARED = re.compile(
    rf'(?P<table_label>{IDENT}):\s*if \((?P<table>{IDENT}) != 0\) \{{\s*'
    rf'(?P<entry>{IDENT}) = \((?P<slot>{IDENT}) \* 4\) \+ (?P=table);\s*'
    rf'(?P<entry_label>{IDENT}):\s*return (?P<base>{IDENT}) \+ \*(?P=entry);\s*\}}\s*'
    rf'goto (?P<fail>{IDENT});'
)


def _trace(items, key, value):
    for item in items:
        if item[0] == 'if' and (test := tree.TEST.fullmatch(item[1])) and test[1] == key:
            branch = item[2] if tree.OPS[test[2]](value, int(test[3], 0)) else item[3]
            yield from _trace(branch or (), key, value)
        else:
            yield item[1] if item[0] == 'plain' else item[4]


def _case(path, prefix, shared, fallback):
    """Validate the complete path up to its terminal jump or fallback."""
    jump = f'jump_{fallback["label"]};'
    terminal = next((i for i, item in enumerate(path) if item.startswith('jump_')), None)
    if terminal is not None:
        if path[terminal] != jump:
            raise tree.Bail
        path = path[:terminal]
    elif path[-2:] == [
        f'label_{fallback["label"]};', f'return {fallback["name"]}({fallback["id"]}, {fallback["table"]});',
    ]:
        path = path[:-2]
    else:
        raise tree.Bail
    if not path:
        return None

    load = re.fullmatch(rf'({IDENT}) = {prefix["index"]} & 0xFFFF;', path[0])
    if not load or len(path) not in (1, 2):
        raise tree.Bail
    if len(path) == 1:
        return None
    slot = load[1]
    guard = ' '.join(path[1].split())
    limit = rf'(?P<limit>{NUMBER})'
    direct = re.fullmatch(
        rf'if \(\({slot} < {limit}\) && \((?P<table>{IDENT}) != 0\)\) \{{ '
        rf'{shared["entry"]} = \({slot} \* 4\) \+ (?P=table); jump_{shared["entry_label"]}; \}}', guard
    )
    if direct:
        return ('table', integer(direct['limit']), direct['table'], None)
    fixed = re.fullmatch(
        rf'if \({slot} < {limit}\) \{{ return \({slot} \* (?P<stride>{NUMBER})\) \+ &(?P<base>{IDENT}); \}}',
        guard,
    )
    if fixed:
        return ('fixed', integer(fixed['limit']), fixed['base'], fixed['stride'])
    if slot != shared['slot']:
        raise tree.Bail
    tail = re.fullmatch(
        rf'if \({slot} < {limit}\) \{{ {shared["table"]} = (?P<table>{IDENT}); (?P<tail>.+) \}}', guard
    )
    if not tail:
        raise tree.Bail
    embedded = ' '.join(shared[0].split())
    embedded = (embedded.replace(f'{shared["table_label"]}:', f'label_{shared["table_label"]};')
                .replace(f'{shared["entry_label"]}:', f'label_{shared["entry_label"]};')
                .replace(f'goto {shared["fail"]};', jump))
    if tail['tail'] not in (f'jump_{shared["table_label"]};', embedded):
        raise tree.Bail
    return ('table', integer(tail['limit']), tail['table'], None)


def candidate(source, name, header, rows):
    if not 120 <= len(rows) <= 230 or not any(mark != ' ' for mark, _, _ in rows):
        return None
    target = tuple(left for _, left, _ in rows if left)
    if target[1:3] != ('andi $v1, $a0, 0xfff', 'andi $a0, $a0, 0xf000'):
        return None
    part = view(source, name)
    if not part or not (end := close(part.clean, part.opening, '{', '}')):
        return None
    part.end = end
    body = part.body
    prefix, shared, fallback = _PREFIX.match(body), _SHARED.search(body), _FALLBACK.search(body)
    if not prefix or not shared or not fallback or fallback['name'] != name:
        return None
    arg, unused = prefix['arg'], prefix['unused']
    signature = re.search(rf'\bvoid \*{re.escape(name)}\(s32 {arg}, s32 {unused}\)\s*$', part.clean[:part.opening])
    if (not signature or re.search(rf'\b{re.escape(name)}\b', header)
            or len(re.findall(rf'\b{re.escape(name)}\b', part.clean)) != 2
            or len(re.findall(rf'\b{unused}\b', body)) != 1
            or fallback['table'] != prefix['table_reg'] or shared['table'] != fallback['table']
            or shared['fail'] != fallback['label'] or integer(fallback['id']) >= 0x1000
            or 'label_' in body or 'jump_' in body or re.search(r'/[*/]', source[part.opening + 1:end - 1])):
        return None
    decision = body[prefix.end():]
    decision = re.sub(rf'(?m)^\s*({IDENT}):', r'label_\1;', decision)
    decision = re.sub(rf'\bgoto ({IDENT});', r'jump_\1;', decision)
    try:
        items = tree._statements(decision, decision, 0, len(decision))
        cases = {value: result for value in range(0, 0x10000, 0x1000)
                 if (result := _case(list(_trace(items, prefix['key'], value)), prefix, shared, fallback))}
    except tree.Bail:
        return None
    if len(cases) < 3 or integer(fallback['id']) >= cases.get(0, (None, 0))[1]:
        return None
    idx = prefix['index']
    lines = [f'void *{name}(s32 {arg}) {{', f'    u16 {idx} = {arg} & 0xfff;', f'    switch ({arg} & 0xf000) {{']
    for value, (kind, limit, table, stride) in cases.items():
        lines.append(f'    case {value:#x}:')
        if kind == 'fixed':
            lines.append(f'        if ({idx} < {limit:#x}U) return (void *)(({idx} * {stride}) + (u32)&{table});')
        else:
            lines.append(f'        if ({idx} < {limit:#x}U && {table} != 0)')
            lines.append(f'            return (void *)({shared["base"]} + ((s32 *){table})[{idx}]);')
        lines.append('        break;')
    lines += ['    }', f'    return {name}({fallback["id"]});', '}']
    return source[:signature.start()] + '\n'.join(lines) + source[end:]
