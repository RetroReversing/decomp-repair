"""Use measured KMC register lifetimes to propose local C edits."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, refs, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_CALL_RESULT = re.compile(
    rf'jal (?P<call>{IDENT})\n[^\n]+\nlw \$v1, [^\n]+\n'
    r'andi \$v0, \$v0, 65535\nsll \$a0, \$v0, \d+\n'
    r'(?:(?:(?:addu|addiu|andi|lui|lw|or|sll) (?!\$v0,)|(?:sb|sh|sw) )[^\n]+\n){1,80}'
    r'lw \$ra, \d+\(\$sp\)\n(?:lw \$s[0-7], \d+\(\$sp\)\n){0,8}'
    r'jr \$ra\naddiu \$sp, \$sp, \d+$'
)

# The same record supplies the signed bound before and after the iteration.
# The target holds the bound base, cursor and counter in separate saved registers.
_WALK = re.compile(
    r'lh \$v0, (?P<bound>\d*)\(\$s2\)\nblez \$v0, (?P<done>\d+)\n'
    r'move \$s1, \$zero\nmove \$s0, \$s2\n'
    r'lw \$v0, (?P<field>\d+)\(\$s0\)\naddu \$a0, \$v0, \$s3\n'
    r'beqz \$a0, (?P<resume>\d+)\nsw \$a0, (?P=field)\(\$s0\)\n'
    rf'move \$a1, \$s3\njal (?P<call>{IDENT})\nmove \$a2, \$s4\n'
    r'lh \$v0, (?P=bound)\(\$s2\)\naddiu \$s1, \$s1, 1\nslt \$v0, \$s1, \$v0\n'
    r'bnez \$v0, (?P<back>\d+)\naddiu \$s0, \$s0, (?P<stride>\d+)\n'
    r'lw \$ra, \d+\(\$sp\)'
)

_WALK_SOURCE = re.compile(
    rf'(?P<count>{IDENT})\s*=\s*0;\s*'
    rf'(?:(?P<zero>{IDENT})\s*=\s*0;\s*)?'
    rf'if\s*\(M2C_FIELD\((?P<base>{IDENT}),\s*s16\s*\*,\s*(?P<bound>{NUMBER})\)'
    r'\s*>\s*(?(zero)(?P=zero)|0)\)\s*\{'
    rf'(?P<loop>\s*(?P<cursor>{IDENT})\s*=\s*(?P=base);\s*(?P<label>{IDENT})\s*:\s*\{{'
    rf'\s*(?P<value>{IDENT})\s*=\s*M2C_FIELD\((?P=cursor),\s*s32\s*\*,\s*(?P<field>{NUMBER})\)'
    rf'\s*\+\s*(?P<bias>{IDENT});\s*M2C_FIELD\((?P=cursor),\s*s32\s*\*,\s*(?P=field)\)'
    rf'\s*=\s*(?P=value);\s*if\s*\(\s*(?P=value)\s*!=\s*0\s*\)\s*\{{'
    rf'\s*(?P<call>{IDENT})\(\s*(?P=value),\s*(?P=bias),\s*(?P<extra>{IDENT})\s*\);\s*\}}'
    rf'\s*(?P=count)\s*\+=\s*1;\s*(?P=cursor)\s*\+=\s*(?P<stride>{NUMBER});\s*\}}'
    r'\s*if\s*\((?P=count)\s*<\s*M2C_FIELD\((?P=base),\s*s16\s*\*,\s*(?P=bound)\)\)'
    r'\s*goto\s+(?P=label);)\s*\}'
)

_COUNTER_SOURCE = _shape('''
    s32 @sum; s32 @second; s32 @first; s32 @a; s32 @b; s32 @updatedsecond; s32 @updatedfirst;
    void *@input; void *@state;
    @input = M2C_FIELD(@object, void **, 0x54);
    @state = M2C_FIELD(@object, void **, 0x60);
    @second = M2C_FIELD(@state, s32 *, 0x178);
    @first = M2C_FIELD(@state, s32 *, 0x174);
    @sum = M2C_FIELD(@input, s32 *, 0x10) + M2C_FIELD(@input, s32 *, 0x14);
    if (@sum >= 0x5DD) {
        @updatedfirst = @first + (@first < 0xFA);
        @a = M2C_FIELD(@output, u8 *, 4) - @updatedfirst;
        M2C_FIELD(@output, u8 *, 4) = (u8) (@a & ((s32) ~@a >> 0x1F));
    } else {
        @updatedfirst = @first - (@first >= 6);
    }
    if (@sum < -0x5DC) {
        @updatedsecond = @second + (@second < 0xFA);
        @b = M2C_FIELD(@output, u8 *, 5) - @updatedsecond;
        M2C_FIELD(@output, u8 *, 5) = (u8) (@b & ((s32) ~@b >> 0x1F));
    } else {
        @updatedsecond = @second - (@second >= 6);
    }
    M2C_FIELD(M2C_FIELD(@object, void **, 0x60), s32 *, 0x178) = @updatedsecond;
    M2C_FIELD(M2C_FIELD(@object, void **, 0x60), s32 *, 0x174) = @updatedfirst;
''')
_COUNTER_WRITES = '''lw $v0, 96($t0)
sw $a2, 376($v0)
lw $v0, 96($t0)
jr $ra
sw $a3, 372($v0)'''

_SLOT_MASK = '''xori $v0, $a1, 6
sltu $v0, $zero, $v0
negu $v0, $v0
and $a1, $a1, $v0
sltiu $v0, $a1, 4'''
_SLOT_TABLE = re.compile(
    r'sll \$v0, \$a1, 1\nlw \$v1, (?P<first>\d+)\(\$a0\)\n'
    r'addu \$v0, \$v0, \$a1\nsll \$v0, \$v0, 2\n'
    rf'lui \$at, %hi\((?P<a>{IDENT})\)\naddu \$at, \$at, \$v0\nsw \$v1, %lo\((?P=a)\)\(\$at\)\n'
    r'lw \$v1, (?P<second>\d+)\(\$a0\)\n'
    rf'lui \$at, %hi\((?P<b>{IDENT})\)\naddu \$at, \$at, \$v0\nsw \$v1, %lo\((?P=b)\)\(\$at\)\n'
    r'lw \$v1, (?P<third>\d+)\(\$a0\)\n'
    rf'lui \$at, %hi\((?P<c>{IDENT})\)\naddu \$at, \$at, \$v0\nsw \$v1, %lo\((?P=c)\)\(\$at\)\n'
    r'jr \$ra\nnop$'
)

# The draft lifted three short-circuit paths over a common destination, using
# a comma expression to make explicit each scheduling copy of the index shift.
_MODE = 'M2C_FIELD(M2C_FIELD(&@state, void **, @stateoffset), u16 *, @modeoffset)'
_FLAGS = 'M2C_FIELD(M2C_FIELD(&@state, void **, @stateoffset), u16 *, @flagoffset)'
_KIND = 'M2C_FIELD(@object, s32 *, @kindoffset)'
_SHIFT = '@slot = @masked * 2'
_SLOT_SOURCE = _shape(f"""s32 @slot; s32 @offset; u16 @mode; u32 @masked;
    @slot = *M2C_FIELD(M2C_FIELD(&@owner, void **, @owneroffset), s32 **, @ownerfield);
    @masked = @slot & -(@slot != 6);
    if ((@masked < 4U) && ((({_MODE} == 2) && !({_FLAGS} & 1) && ({_SHIFT}, ({_KIND} == 3))) ||
        ((@mode = {_MODE}, (@mode == {_KIND})) && ({_FLAGS} & 1) && ({_SHIFT}, (@mode == 2))) ||
        ((@mode = {_MODE}, (@mode == 1)) && ({_SHIFT}, ({_KIND} == @mode))))) {{
        @offset = (@slot + @masked) * 4;
""", numbers=('stateoffset', 'modeoffset', 'flagoffset', 'kindoffset', 'owneroffset', 'ownerfield'))
_SLOT_STORE = re.compile(rf'\*\(&({IDENT}) \+ ({IDENT})\) = M2C_FIELD\(({IDENT}), s32 \*, ({NUMBER})\); ')



def variants(source, name, header, rows):
    if not 16 <= len(rows) <= 128 or not any(mark != ' ' for mark, _, _ in rows):
        return []
    target = normalized_integer_lines(left for _, left, _ in rows if left)
    trace = '\n'.join(target)
    result = _CALL_RESULT.search(trace)
    walk = _WALK.search(trace)
    table = _SLOT_TABLE.search(trace) if _SLOT_MASK in trace and target.count('sll $v0, $a1, 1') == 3 else None
    counters = (trace.endswith(_COUNTER_WRITES)
                and 'addu $a3, $a3, $v1' in target and 'addu $a2, $a2, $v1' in target)
    if not (result or walk or counters or table) or not (part := view(source, name)):
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    part.end = end
    if result and (fixed := _return_result(part, name, header, rows, result['call'])):
        return [('measured_narrow_call_return', fixed)]
    if walk and (fixed := _guarded_walk(part, name, walk, trace)):
        return [('measured_guarded_walk_scope', fixed)]
    if counters and (fixed := _in_place_counters(part, name)):
        return [('measured_paired_counter_updates', fixed)]
    if table and (fixed := _slot_records(part, name, table, target)):
        return [('measured_slot_record_stride', fixed)]
    return []


def _return_result(part, name, header, rows, callee):
    # A destructive reuse of the candidate's return register must disagree with the target.
    if not any(mark != ' ' and re.match(r'andi \$(?!v0\b)\w+, \$v0, (?:0xffff|65535)$', right, re.I)
               and left in ('andi $v0, $v0, 0xffff', 'andi $v0, $v0, 65535') for mark, left, right in rows):
        return None
    signature = re.search(rf'\bvoid(?=\s+{re.escape(name)}\s*\([^()]*\)\s*$)', part.clean[:part.opening])
    if not signature or re.search(rf'\b{re.escape(name)}\s*\(', header + '\n' + part.clean[:signature.start()] + '\n' + part.clean[part.end:]):
        return None
    if re.search(r'\b(?:return|goto)\b', part.body):
        return None
    assignment = re.search(
        rf'\b(?P<value>{IDENT})\s*=\s*(?P<call>{callee}\([^()]*\))\s*&\s*(?P<mask>{NUMBER});',
        part.body,
    )
    if not assignment or integer(assignment['mask']) != 65535:
        return None
    body_start = part.opening + 1
    assign_start = body_start + assignment.start()
    prefix = part.clean[body_start:assign_start]
    if prefix.count('{') != prefix.count('}') or prefix.rstrip()[-1:] not in (';', '}'):
        return None
    decl = next((item for item in locals_for(part) if item['name'] == assignment['value'] and item['type'] == 's32'), None)
    if (not decl or part.clean[part.opening + 1:decl.start()].count('{')
            or any(re.match(r'\s*(?:(?:[+*/%&|^-]|<<|>>)?=(?!=)|\+\+|--)', part.clean[use.end():])
                   or re.search(r'(?:\+\+|--)\s*$', part.clean[:use.start()])
                   for use in refs(part, decl) if use.start() != assign_start)):
        return None
    call_start = body_start + assignment.start('call')
    call = part.source[call_start:body_start + assignment.end('call')]
    return edit(part.source, [
        (*signature.span(), 's32'),
        (call_start, body_start + assignment.end('mask'), '(u16)' + call),
        (part.end - 1, part.end - 1, f'    return {assignment["value"]};\n'),
    ])


def _guarded_walk(part, name, target, trace):
    match = _WALK_SOURCE.search(part.clean, part.opening + 1, part.end - 1)
    if not match or any(integer(match[key]) != int(target[key] or '0') for key in ('bound', 'field', 'stride')):
        return None
    args = re.search(rf'\bvoid\s+{re.escape(name)}\(\s*void\s*\*\s*({IDENT}),\s*s32\s+({IDENT}),'
                     rf'\s*(?:s32|M2C_UNK)\s+({IDENT})\s*\)\s*$', part.clean[:part.opening])
    if not args or args.groups() != tuple(match[key] for key in ('base', 'bias', 'extra')):
        return None
    roles = [match[key] for key in ('base', 'bias', 'extra', 'cursor', 'label', 'value', 'count', 'zero', 'call')
             if match[key]]
    if len(set(roles)) != len(roles) or match['call'] != target['call'] or target['call'] == name:
        return None
    start = trace[:target.start()].count('\n')
    if [int(target[key]) for key in ('back', 'resume', 'done')] != [4 * (start + offset) for offset in (4, 11, 16)]:
        return None
    if len(re.findall(rf'\b{match["label"]}\b', part.body)) != 2:
        return None
    start, end = match.span('loop')
    return edit(part.source, [(start, start, '\n            do {'),
                              (end, end, '\n            } while (0);')])


def _in_place_counters(part, name):
    match = _COUNTER_SOURCE.fullmatch(' '.join(part.body.split()))
    args = re.search(rf'\bvoid\s+{re.escape(name)}\(\s*void\s*\*\s*({IDENT}),\s*void\s*\*\s*({IDENT})\s*\)\s*$',
                     part.clean[:part.opening])
    if not match or not args or args.groups() != (match['object'], match['output']):
        return None
    roles = match.groupdict()
    if len(set(roles.values())) != len(roles):
        return None
    changes = []
    for previous, updated in (('first', 'updatedfirst'), ('second', 'updatedsecond')):
        old, new = match[previous], match[updated]
        pattern = re.compile(rf'(?P<decl>\bs32\s+{new}\s*;)|'
                             rf'\b{new}\s*=\s*{old}\s*(?P<op>[+-])|\b{new}\b')
        for hit in pattern.finditer(part.clean, part.opening + 1, part.end - 1):
            replacement = old
            if hit['decl']:
                replacement = ''
            elif hit['op']:
                replacement = f'{old} {hit["op"]}='
            changes.append((*hit.span(), replacement))
    return edit(part.source, changes)

def _slot_records(part, name, table, target):
    body = normalized_integer_lines((part.body,))[0]
    source = _SLOT_SOURCE.match(body)
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT})\)\s*$', part.clean[:part.opening])
    if not source or not signature or signature[1] != source['object']:
        return None
    stores = tuple(_SLOT_STORE.finditer(body, source.end()))
    if len(stores) != 3 or body[source.end():] != ' ' + ''.join(store[0] for store in stores) + '}':
        return None
    symbols = [table[key] for key in ('a', 'b', 'c')]
    fields = [table[key] for key in ('first', 'second', 'third')]
    mode = source['modeoffset']
    flags = source['flagoffset']
    kind = source['kindoffset']
    if not {f'lhu $v1, {mode}($a2)', f'lhu $a2, {mode}($v1)', f'lhu $v1, {mode}($v0)',
            f'lhu $v0, {flags}($a2)', f'lhu $v0, {flags}($v1)',
            f'lw $v1, {kind}($a0)', f'lw $v0, {kind}($a0)'}.issubset(target):
        return None
    roles = [source[key] for key in ('slot', 'offset', 'mode', 'masked', 'state', 'owner', 'object')] + symbols
    if len(set(roles)) != len(roles):
        return None
    if any(store.groups() != (symbol, source['offset'], source['object'], field)
           for store, symbol, field in zip(stores, symbols, fields)):
        return None
    slot, mode = source['slot'], source['mode']
    lookup, flags, kind = (re.sub(r'@([a-z]+)', lambda role: source[role[1]], expression)
                           for expression in (_MODE, _FLAGS, _KIND))
    guards = (
        f'({lookup} == 2) && !({flags} & 1) && ({kind} == 3)',
        f'({mode} = {lookup}, ({mode} == {kind})) && ({flags} & 1) && ({mode} == 2)',
        f'({mode} = {lookup}, ({mode} == 1)) && ({kind} == {mode})',
    )
    # Keep each short-circuit path's loads, and let GCC share the identical writes.
    writes = ''.join(f'            *(&{symbol} + {slot} * 3) = M2C_FIELD({source["object"]}, s32 *, {field});\n'
                     for symbol, field in zip(symbols, fields))
    branches = ' else '.join(f'if ({guard}) {{\n{writes}        }}' for guard in guards)
    mask = re.search(rf'\b{source["masked"]}\s*=\s*{slot}\s*&', part.body)
    if not mask:
        return None
    start = part.opening + 1 + mask.start()
    fixed = f'{slot} &= -({slot} != 6);\n    if ((u32){slot} < 4) {{\n        {branches}\n    }}\n'
    return edit(part.source, [(start, part.end - 1, fixed)])
