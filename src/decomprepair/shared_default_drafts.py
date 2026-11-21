"""Recover a switch whose default block contains cases emitted outside the switch by m2c."""

import re
from collections import defaultdict

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names

TARGET = r'\.L\w+'
JUMP_TABLE = re.compile(
    rf'addiu (?P<selector>\$a[01]), (?P=selector), -(?P<first>{NUMBER})\n'
    rf'sltiu (?P<index>\$\w+), (?P=selector), (?P<count>{NUMBER})\n'
    rf'beqz (?P=index), (?P<default>{TARGET})\n'
    rf'sw \$ra, (?P<ra>{NUMBER})\(\$sp\)\n'
    r'sll (?P=index), (?P=selector), 2\n'
    rf'lui \$at, %hi\((?P<table>{IDENT})\)\n'
    r'addu \$at, \$at, (?P=index)\n'
    r'lw (?P=index), %lo\((?P=table)\)\(\$at\)\n'
    r'jr (?P=index)\nnop'
)
DRAFT = re.compile(
    rf'u32 (?P<offset>{IDENT}); (?P=offset) = (?P<selector>{IDENT}) - (?P<first>{NUMBER}); '
    rf'if \((?P=offset) < (?P<count>{NUMBER})\) {{ switch \((?P=selector)\) {{ (?P<cases>[^{{}}]+) }} }}'
    rf' else {{ (?P<default>[^{{}}]+) }}'
)
GROUP = re.compile(rf'(?P<labels>(?:case {NUMBER}: )+)(?P<callee>{IDENT})\((?P<arg>{IDENT})\);(?: (?P<exit>return;) ?)?')


def _instructions(asm):
    """Labels may be present in disassembly only through an instruction's address comment."""
    lines, labels = [], {}
    for raw in abi_register_names(asm).splitlines():
        if address := re.match(r'\s*/\*\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]{8})\s+[0-9A-Fa-f]+\s*\*/', raw):
            labels.setdefault('.L'+address[1].upper(),len(lines))
        line = ' '.join(re.sub(r'/\*.*?\*/|#.*','',raw).split())
        if re.fullmatch(rf'{TARGET}:',line):
            labels[line[:-1]]=len(lines)
        elif line and not line.startswith(('.', 'glabel ', 'endlabel ')):
            lines.append(line)
    return lines, labels


def _dispatch(lines):
    if not lines or not re.fullmatch(rf'addiu \$sp, \$sp, -{NUMBER}', lines[0]):
        return None
    return JUMP_TABLE.fullmatch('\n'.join(lines[1:11]))


def applies(asm):
    """Cheap cache-key gate for the supported ranges and dispatch sequence."""
    return ('sltiu' in asm and '%hi(' in asm and _dispatch(_instructions(asm)[0]) is not None)


def _entries(data, table, count):
    key = re.search(rf'(?m)^\s*(?:dlabel\s+{table}|{table}:)\s*$', data or '')
    if not key:
        return None
    words = re.match(rf'(?:[ \t]*\n[ \t]*\.word[ \t]+{TARGET}[ \t]*){{{count}}}(?=\n|$)', data[key.end():])
    return re.findall(TARGET, words[0]) if words else None


def _blocks(lines, labels, offsets, mode, default):
    # Every target is a direct call with an empty delay slot and the same epilogue.
    epilogue = len(lines)-3
    size = integer(lines[0].rsplit(' -',1)[1])
    if lines[epilogue:epilogue+2] != [f'lw $ra, {mode["ra"]}($sp)','jr $ra']:
        return None
    if not (restore := re.fullmatch(rf'addiu \$sp, \$sp, ({NUMBER})',lines[-1])) or integer(restore[1]) != size:
        return None
    addresses = [labels.get(label, -1) for label in offsets]
    fallback = labels.get(default, -1)
    groups = defaultdict(list)
    for case, position in enumerate(addresses,integer(mode['first'])):
        groups[position].append(case)
    if fallback not in groups or min(groups) != 11:
        return None
    order = sorted(groups)
    result = []
    for i, position in enumerate(order):
        end = order[i+1] if i+1 < len(order) else epilogue
        if position < 11 or end > epilogue:
            return None
        block = lines[position:end]
        if len(block) not in (2,4) or block[1] != 'nop' or not (call := re.fullmatch(rf'jal ({IDENT})',block[0])):
            return None
        if len(block) == 4:
            jump = re.fullmatch(rf'j ({TARGET})',block[2])
            if not jump or labels.get(jump[1]) != epilogue or block[3] != 'nop':
                return None
        elif end != epilogue:
            return None
        result.append((tuple(groups[position]),call[1],position==fallback))
    return result


def _source_groups(text, index, default=False):
    cursor, groups = 0,[]
    while hit := GROUP.match(text,cursor):
        if hit['arg'] != index or (not default and not hit['exit']):
            return None
        cases = tuple(sorted(integer(value) for value in re.findall(rf'case ({NUMBER}):',hit['labels'])))
        groups.append((cases,hit['callee'],default))
        cursor = hit.end()
    return groups if cursor == len(text) and groups else None


def rewrite(source, name, asm, data, context=''):
    """Return a single switch only when the guard, table, and all case bodies agree."""
    if not data or 'switch (' not in source or '} else {' not in source or 'case ' not in source:
        return None
    part = view(source,name)
    if part is None:
        return None
    end = len(part.clean[:part.end].rstrip())-1
    draft = DRAFT.fullmatch(' '.join(part.clean[part.opening+1:end].split()))
    if not draft:
        return None
    lines, labels = _instructions(asm)
    mode = _dispatch(lines)
    if not mode or integer(mode['first']) != integer(draft['first']):
        return None
    count = integer(mode['count'])
    if not 2 <= count <= 32 or integer(draft['count']) != count:
        return None
    offsets = _entries(data, mode['table'], count)
    ordinary = _source_groups(draft['cases'],draft['offset'])
    fallback = _source_groups(draft['default'],draft['offset'],default=True)
    if not offsets or not ordinary or not fallback or len(fallback) != 1:
        return None
    blocks = _blocks(lines,labels,offsets,mode,mode['default'])
    if not blocks or sorted(blocks) != sorted(ordinary+fallback):
        return None

    selector = draft['selector']
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(s32 {selector}\)\s*$',part.clean[:part.opening])
    if not signature or selector != 'arg'+mode['selector'][-1]:
        return None
    params = f's32 {selector}'
    if mode['selector'] == '$a1':
        if re.search(r'\barg0\b',part.clean+'\n'+context):
            return None
        params = 's32 arg0, '+params
    edits = []
    callees = {callee for _,callee,_ in blocks}
    for callee in callees:
        if re.search(rf'\b{callee}\b',context):
            return None
        prototype = re.search(rf'(?m)^M2C_UNK {callee}(\(u32\));[ \t]*/\* extern \*/[ \t]*$',source[:signature.start()])
        if not prototype:
            return None
        edits.append((*prototype.span(1),'()'))
    body = [f'void {name}({params}) {{',f'    switch ({selector}) {{']
    for cases,callee,is_default in blocks:
        if is_default:
            body.append('    default:')
        body.extend(f'    case {case}:' for case in cases)
        body.extend((f'        {callee}();','        break;'))
    body.extend(('    }','}'))
    return edit(source,edits+[(signature.start(),end+1,'\n'.join(body))])


_MASKED_DISPATCH = re.compile(
    rf'^andi (?P<input>\$a[0-3]), (?P=input), (?P<mask>{NUMBER})\n'
    rf'sltiu (?P<index>\$\w+), (?P=input), (?P<count>{NUMBER})\n'
    rf'beqz (?P=index), (?P<default>{TARGET})\n(?:nop\n)?'
    r'sll (?P=index), (?P=input), 2\n'
    rf'lui \$at, %hi\((?P<table>{IDENT})\)\n'
    r'addu \$at, \$at, (?P=index)\n'
    r'lw (?P=index), %lo\((?P=table)\)\(\$at\)\njr (?P=index)\nnop(?:\n|$)'
)
_MASKED_SOURCE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<type>u32)[ \t]+(?P<temp>{IDENT});\s+'
    rf'(?:(?:{IDENT} = {IDENT};)\s+)?(?P=temp) = (?P<arg>{IDENT}) & (?P<mask>{NUMBER});\s+'
    r'switch \((?P=temp)\) \{\n(?P<body>[^{}]+)^[ \t]*\}'
)
_CASE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:case (?P<value>{NUMBER})|(?P<default>default)):[ \t]*$')


def explicit_default_labels(source, name, asm, data):
    """Restore leading case labels whose destinations are the dispatch guard's default."""
    if not data or 'u32 ' not in source or 'switch (' not in source or 'andi' not in asm:
        return None
    part = view(source, name)
    if not part or not (switch := _MASKED_SOURCE.search(part.clean, part.opening + 1, part.end)):
        return None
    if len(re.findall(r'\bswitch\s*\(', part.body)) != 1 or len(re.findall(rf'\b{switch["temp"]}\b', part.body)) != 3:
        return None
    lines, labels = _instructions(asm)
    dispatch = _MASKED_DISPATCH.match('\n'.join(lines))
    if not dispatch or integer(dispatch['mask']) not in (255, 65535):
        return None
    if integer(dispatch['mask']) != integer(switch['mask']) or switch['arg'] != 'arg' + dispatch['input'][-1]:
        return None
    count = integer(dispatch['count'])
    if not 2 <= count <= 32:
        return None
    targets = _entries(data, dispatch['table'], count)
    fallback = labels.get(dispatch['default'])
    if not targets or fallback is None or any(target not in labels for target in targets):
        return None
    cases = list(_CASE.finditer(switch['body']))
    values = [integer(c['value']) for c in cases if c['value']]
    if not values or values != list(range(values[0], count)) or values[0] < 1:
        return None
    if any((labels[target] == fallback) != (number < values[0]) for number, target in enumerate(targets)):
        return None
    if len({labels[target] for target in targets[values[0]:]}) != len(values):
        return None

    defaults = [c for c in cases if c['default']]
    if defaults and (len(defaults) != 1 or cases[-1] != defaults[0]):
        return None
    # The flat bodies m2c emits here terminate every arm. With no explicit default,
    # insert a standalone break before the first case, preserving all active arms.
    for index, case in enumerate(cases):
        end = cases[index+1].start() if index+1 < len(cases) else len(switch['body'])
        if not re.search(r'\b(?:break|return(?:\s+[^;]+)?)\s*;\s*$', switch['body'][case.end():end]):
            return None
    where = (defaults[0] if defaults else cases[0])
    indent = where['indent']
    added = ''.join(f'{indent}case {number}:\n' for number in range(values[0]))
    if not defaults:
        added += indent + '    break;\n'
    at = switch.start('body') + where.start()
    return edit(source, [(at, at, added), (*switch.span('type'), 's32')])
