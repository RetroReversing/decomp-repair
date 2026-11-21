"""Recover KMC drafts with incorrect setup around an otherwise matching call."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_MASK_TAIL = re.compile(
    rf'move \$a0, \$s2\njal (?P<call>{IDENT})\nmove \$a1, \$zero\n'
    rf'andi \$v0, \$s1, (?P<mask>\d+)\nbeqz \$v0, \d+\nmove \$a0, \$s2\n'
    rf'j (?P<name>{IDENT})\+\d+\naddiu \$a1, \$zero, 1\nmove \$a1, \$zero\njal (?P=call)\nnop'
)
_MASK_DRAFT = re.compile(
    rf'(?P<first>^[ \t]*(?P<test>{IDENT}) = (?P<value>{IDENT}) & (?P<mask>{NUMBER});)\s*'
    rf'if \((?P=value) & {NUMBER}\) \{{[^{{}}]+?'
    rf'(?P<second>^[ \t]*(?P=test) = (?P=value) & (?P=mask);)\s*\}}\s*'
    rf'(?P<tail>if \((?P=test) != 0\) \{{\s*(?P<arg>{IDENT}) = 1;'
    rf'\s*(?P<call>{IDENT})\((?P<context>{IDENT}), (?P=arg)\);\s*\}}\s*else\s*\{{'
    r'\s*(?P=arg) = 0;\s*(?P=call)\((?P=context), (?P=arg)\);\s*\})',
    re.M,
)
_KEEP_CONTEXT = re.compile(
    r'addiu \$sp, \$sp, -24\nsw \$ra, 16\(\$sp\)\nlw \$v0, (?P<record>\d+)\(\$a0\)\n'
    r'lw \$v1, (?P<first>\d+)\(\$v0\)\nlw \$a3, (?P<second>\d+)\(\$v0\)\n'
    r'subu \$v1, \$v1, \$a3\nmult \$a1, \$v1\nmflo \$v1\nlui \$v0, 20971\nori \$v0, \$v0, 34079\n'
    r'(?:[^\n]+\n)*?lw \$v0, (?P=record)\(\$a0\)\n'
    rf'jal (?P<call>{IDENT})\nlw \$a1, (?P<field>\d+)\(\$v0\)\n'
    r'lw \$ra, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)
_KEEP_LOADS = re.compile(
    rf'(?P<base>{IDENT}) = M2C_FIELD\((?P<context>{IDENT}), void \*\*, (?P<record>{NUMBER})\);\s*'
    rf'(?P<save>(?P<value>{IDENT}) = M2C_FIELD\((?P=base), s32 \*, (?P<second>{NUMBER})\);)\s*'
    rf'(?P<obj>{IDENT}) = M2C_FIELD\((?P=context), void \*\*, {NUMBER}\);\s*'
    rf'M2C_FIELD\((?P=obj), s32 \*, {NUMBER}\) = '
    rf'\(s32\) \(\(\({IDENT} \* \((?P<read>M2C_FIELD\((?P=base), s32 \*, (?P<first>{NUMBER})\))'
    r' - (?P=value)\)\) / 100\) \+ (?P=value)\);'
)
_GLOBAL_TARGET = re.compile(
    rf'lw \$v1, \(\$s1\)\nlhu \$v0, (?P<halfword>\d+)\(\$v1\)\n'
    rf'lui \$a0, %hi\((?P<global>{IDENT})\)\nlw \$a0, %lo\((?P=global)\)\(\$a0\)\n'
    r'move \$s0, \$zero\naddiu \$v0, \$v0, -(?P<delta>\d+)\nsh \$v0, (?P=halfword)\(\$v1\)\n'
    rf'lw \$a2, (?P<field>\d+)\(\$a0\)\naddiu \$a1, \$zero, (?P<second>\d+)\n'
    rf'jal (?P<call>{IDENT})\naddiu \$a0, \$zero, (?P<first>\d+)'
)
_GLOBAL_DRAFT = re.compile(
    rf'(?P<base>{IDENT}) = M2C_FIELD\({IDENT}, void \*\*, 0\);\s*'
    rf'(?P<insert>^[ \t]*){IDENT} = 0;\s*'
    rf'M2C_FIELD\((?P=base), u16 \*, (?P<halfword>{NUMBER})\) = \(u16\) '
    rf'\(M2C_FIELD\((?P=base), u16 \*, (?P=halfword)\) - (?P<delta>{NUMBER})\);\s*'
    rf'(?P<call>{IDENT})\((?P<first>{NUMBER}), (?P<second>{NUMBER}), '
    rf'M2C_FIELD\((?P<global>{IDENT}), s32 \*, (?P<field>{NUMBER})\)\);', re.M,
)
_EVENT_TARGET = re.compile(
    rf'addiu \$a0, \$s4, (?P<queue>\d+)\naddiu \$a1, \$sp, (?P<record>\d+)\n'
    rf'move \$a2, \$s5\naddiu \$v0, \$zero, (?P<tag>\d+)\nsh \$v0, (?P=record)\(\$sp\)\n'
    rf'jal (?P<call>{IDENT})\nsw \$s3, (?P<payload>\d+)\(\$sp\)'
)
_EVENT_DRAFT = re.compile(
    rf'(?P<tagvar>sp[\dA-Fa-f]+) = (?P<tag>{NUMBER});\s*'
    rf'(?P<data>sp[\dA-Fa-f]+) = (?P<input>{IDENT});\s*'
    rf'(?P<call>{IDENT})\((?P<queue>{IDENT}) \+ (?P<delta>{NUMBER}), &(?P=tagvar), (?P<delay>{IDENT})\);\s*$'
)


def variants(source, name, header, rows):
    if not 34 <= len(rows) <= 85:
        return []
    changed = {normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' '}
    if not changed:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    if ((hit := _MASK_TAIL.search(target)) and hit['name'] == name
            and (f'andi $v0, $s1, {hit["mask"]}', '') in changed):
        family, fixed = 'measured_mask_at_final_call', _mask(part, hit)
    elif ((hit := _KEEP_CONTEXT.fullmatch(target)) and ('', 'move $a3, $a1') in changed
          and (f'lw $a1, {hit["field"]}($v0)', f'lw $a0, {hit["field"]}($v0)') in changed):
        family, fixed = 'measured_keep_first_call_argument', _keep_context(part, name, header, hit)
    elif ((hit := _GLOBAL_TARGET.search(target))
          and (f'sh $v0, {hit["halfword"]}($v1)', '') in changed
          and ('', f'sh $v0, {hit["halfword"]}($v1)') in changed):
        family, fixed = 'measured_global_pointer_before_update', _global(part, header, hit)
    elif (hit := _EVENT_TARGET.search(target)):
        wanted, trial = normalized_integer_lines(rows[0][1:])
        wanted_frame = re.fullmatch(r'addiu \$sp, \$sp, -(\d+)', wanted)
        trial_frame = re.fullmatch(r'addiu \$sp, \$sp, -(\d+)', trial)
        padding = int(wanted_frame[1]) - int(trial_frame[1]) if wanted_frame and trial_frame else 0
        if (padding != 8 or (f'sw $s3, {hit["payload"]}($sp)', '') not in changed):
            return []
        family, fixed = 'measured_delayed_stack_record_payload', _event(part, name, header, hit, padding)
    else:
        return []
    return [(family, fixed)] if fixed else []


def _mask(part, target):
    draft = _MASK_DRAFT.search(part.body)
    if not draft or integer(draft['mask']) != int(target['mask']) or draft['call'] != target['call']:
        return None
    removed = ' '.join(draft[key] for key in ('first', 'second', 'tail'))
    for key in ('arg', 'test'):
        references = rf'\b{draft[key]}\b'
        if len(re.findall(references, part.body)) != len(re.findall(references, removed)) + 1:
            return None
    line = part.body.rfind('\n', 0, draft.start('tail')) + 1
    indent = part.body[line:draft.start('tail')]
    if indent.strip():
        return None
    call = f'{draft["call"]}({draft["context"]}'
    tail = (
        f'if ({draft["value"]} & {draft["mask"]}) {{\n'
        f'{indent}    {call}, 1);\n'
        f'{indent}}} else {{\n'
        f'{indent}    {call}, 0);\n'
        f'{indent}}}'
    )
    start = part.opening + 1
    return edit(part.source, [(start + draft.start(key), start + draft.end(key), replacement)
                              for key, replacement in [('first', ''), ('second', ''), ('tail', tail)]])


def _keep_context(part, name, header, target):
    draft = _KEEP_LOADS.search(part.body)
    local = '__repair_first_value'
    call = target['call']
    if (not draft or local in part.clean + _blank(header) or name == call
            or any(integer(draft[key]) != int(target[key]) for key in ('record', 'first', 'second'))):
        return None
    prototype = re.search(rf'\b(?:M2C_UNK|void|s32)\s+{call}\((s32, void \*, s32)\);',
                          part.clean[:part.opening])
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*{draft["context"]}, s32 {IDENT}\)\s*$',
                    part.clean[:part.opening])
    invoke = re.search(
        rf'\b{call}\((?P<field>M2C_FIELD\(M2C_FIELD\({draft["context"]}, void \*\*, '
        rf'{draft["record"]}\), s32 \*, (?P<offset>{NUMBER})\)), {draft["obj"]}, {draft["value"]}\);\s*$',
        part.body,
    )
    if (not prototype or not sig or not invoke or integer(invoke['offset']) != int(target['field'])
            or len(re.findall(rf'\b{call}\b', part.clean + _blank(header))) != 2):
        return None
    start = part.opening + 1
    return edit(part.source, [
        (*prototype.span(1), 'void *, s32'),
        (start, start, f'\n    s32 {local};'),
        (start + draft.start('save'), start + draft.start('save'), f'{local} = {draft["read"]};\n    '),
        (start + draft.start('read'), start + draft.end('read'), local),
        (start + invoke.start(), start + invoke.end(), f'{call}({draft["context"]}, {invoke["field"]});\n'),
    ])


def _global(part, header, target):
    draft = _GLOBAL_DRAFT.search(part.body)
    local = '__repair_global_base'
    if (not draft or local in part.clean + _blank(header)
            or any(draft[key] != target[key] for key in ('global', 'call'))
            or any(integer(draft[key]) != int(target[key]) for key in ('halfword', 'delta', 'field', 'first', 'second'))
            or not re.search(rf'\bextern void\s*\*{target["global"]}\s*;', part.clean[:part.opening])):
        return None
    start = part.opening + 1
    insert = start + draft.end('insert')
    return edit(part.source, [
        (start, start, f'\n    void *{local};'),
        (insert, insert, f'{local} = {draft["global"]};\n{draft["insert"]}'),
        (start + draft.start('global'), start + draft.end('global'), local),
    ])


def _event(part, name, header, target, padding):
    draft = _EVENT_DRAFT.search(part.body)
    record = '__repair_event'
    if not draft or record in part.clean + _blank(header):
        return None
    tagvar, data = draft['tagvar'], draft['data']
    head = re.match(rf'\s*s16 {tagvar};\s*void \*{data};', part.body)
    sig = re.search(
        rf'\bvoid\s+{re.escape(name)}\(void \*{draft["queue"]}, void \*{draft["input"]}, s32 {draft["delay"]}\)\s*$',
        part.clean[:part.opening],
    )
    if (not sig or not head or draft['call'] != target['call']
            or integer(draft['tag']) != int(target['tag']) or integer(draft['delta']) != int(target['queue'])
            or int(tagvar[2:], 16) != int(target['record']) or int(data[2:], 16) != int(target['payload'])
            or int(target['record']) + 4 != int(target['payload'])
            or len(re.findall(rf'\b{tagvar}\b', part.body)) != 3
            or len(re.findall(rf'\b{data}\b', part.body)) != 2):
        return None
    start = part.opening + 1
    fields = ('event_tag', 'event_payload', 'event_tail')
    if any(re.search(rf'(?m)^\s*#\s*define\s+{field}\b', part.source + '\n' + header) for field in fields):
        return None
    fixed = (
        f'{record}.event_tag = {draft["tag"]};\n    {record}.event_payload = {draft["input"]};\n'
        f'    {draft["call"]}({draft["queue"]} + {draft["delta"]}, (s16 *) &{record}, {draft["delay"]});\n'
    )
    return edit(part.source, [
        (start, start + head.end(),
         f'\n    struct {{ s16 event_tag; void *event_payload; s32 event_tail[{padding // 4}]; }} {record};'),
        (start + draft.start(), start + draft.end(), fixed),
    ])
