"""Use measured MIPS differences to recover cursor and call operand ordering."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .shared_default_drafts import _instructions

_MOVE = 'o'


def variants(source, name, header, rows, asm=''):
    changed = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if not changed or len(changed) > 9:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or '__repair_cursor_' in source + header:
        return []
    if len(changed) == 2:
        for family, proposal in (
            ('staged_call_clamp', _call_clamp),
            ('context_slot_reload', _context_reload),
        ):
            if candidate := proposal(part, rows, changed, end):
                return [(family, candidate)]
    elif len(changed) == 9:
        if candidate := _masked_list(part, name, rows, asm, end):
            return [('masked_list_cursor', candidate)]
        if candidate := _record_cursor(part, name, rows, asm, end):
            return [('paired_record_cursor', candidate)]
    return []


def _moved(rows, changed):
    earlier, later = (rows[i] for i in changed)
    if earlier[0] != _MOVE or later[0] != _MOVE:
        return None
    if earlier[1] and earlier[1] == later[2] and not earlier[2] and not later[1]:
        return earlier[1], True
    if earlier[2] and earlier[2] == later[1] and not earlier[1] and not later[2]:
        return earlier[2], False
    return None


def _call_clamp(part, rows, changed, end):
    first, last = changed
    if first < 2 or last + 4 >= len(rows) or last - first != 4:
        return None
    moved = _moved(rows, changed)
    if not moved or moved[1] or not re.fullmatch(rf'addiu \$a0, \$sp, {NUMBER}', moved[0]):
        return None
    ops = normalized_integer_lines(row[1] for row in rows[first + 1:last])
    if tuple(ops) != ('nor $v1, $zero, $v0', 'sra $v1, $v1, 31', 'and $v0, $v0, $v1'):
        return None
    before = re.fullmatch(rf'jal ({IDENT})', rows[first - 2][1])
    symbol = re.fullmatch(rf'lui \$a1, %hi\(({IDENT})\)', rows[last + 1][1])
    after = re.fullmatch(rf'jal ({IDENT})', rows[last + 3][1])
    if (not before or not symbol or not after or rows[first - 1][1] != 'nop'
            or rows[last + 2][1] != f'addiu $a1, $a1, %lo({symbol[1]})'
            or rows[last + 4][1] != 'andi $a2, $v0, 0xffff'):
        return None
    shape = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<value>{IDENT})\s*=\s*{before[1]}\([^;]*\);\n'
        rf'(?P=indent){after[1]}\(&(?P<buffer>{IDENT}(?:\.{IDENT})*), &{symbol[1]}, '
        rf'(?P<expression>(?P=value) & \(\(s32\) ~(?P=value) >> (?:31|0x1F)\)) & 0xFFFF\);'
    )
    hit = shape.search(part.clean, part.opening + 1, end)
    if not hit or not re.search(rf'\bs32\s+{hit["value"]}\s*;', part.body):
        return None
    if (re.search(rf'&\s*{hit["value"]}\b', part.body)
            or re.search(rf'\b{hit["value"]}\b', part.clean[hit.end():end])):
        return None
    call_start = part.clean.index('\n', hit.start()) + 1
    assignment = f'{hit["indent"]}{hit["value"]} &= (s32) ~{hit["value"]} >> 31;\n'
    return edit(part.source, [(call_start, call_start, assignment), (*hit.span('expression'), hit['value'])])


def _context_reload(part, rows, changed, end):
    first, last = changed
    if first < 4 or last + 5 >= len(rows) or last - first != 3:
        return None
    moved = _moved(rows, changed)
    if not moved or not moved[1]:
        return None
    old_call = re.fullmatch(rf'jal ({IDENT})', rows[first - 4][1])
    global_load = re.fullmatch(rf'lw \$a0, %lo\(({IDENT})\)\(\$a0\)', rows[first - 1][1])
    store = re.fullmatch(rf'sw \$s0, ({NUMBER})\(\$a0\)', moved[0])
    new_call = re.fullmatch(rf'jal ({IDENT})', rows[last + 4][1])
    if not old_call or not global_load or not store or not new_call or rows[first - 3][1] != 'move $s0, $a0':
        return None
    symbol, offset = global_load[1], integer(store[1])
    if rows[first - 2][1] != f'lui $a0, %hi({symbol})' or rows[first + 1][1] != f'lw $a1, {store[1]}($a0)':
        return None
    if [rows[i][1] for i in (first + 2, last + 1, last + 2, last + 3, last + 5)] != [
            'addiu $v1, $zero, 1', 'sh $v1, ($a0)', 'lw $v1, 4($a1)', 'sw $v1, 0xc($a0)', 'move $a0, $v0']:
        return None
    record = rf'\(\((?P<type>{IDENT})\*\){symbol}\)->'
    same = rf'\(\((?P=type)\*\){symbol}\)->'
    shape = re.compile(
        rf'(?m)^[ \t]*(?P<status>{IDENT}) = {old_call[1]}\(\);\n'
        rf'(?P<load>[ \t]*(?P<local>{IDENT}) = {record}field_{offset:X};\n)'
        rf'[ \t]*{same}field_{offset:X} = (?P<mode>{IDENT});\n'
        rf'(?P<flag>[ \t]*{same}field_0 = 1;\n)'
        rf'[ \t]*{same}field_C = \(s32\) M2C_FIELD\((?P=local), s32 \*, 4\);\n'
        rf'[ \t]*{new_call[1]}\((?P=status), (?P=local)\);'
    )
    hit = shape.search(part.clean, part.opening + 1, end)
    if not hit or len(re.findall(rf'\b{hit["local"]}\b', part.body)) != 4:
        return None
    return edit(part.source, [(*hit.span('load'), ''), (hit.end('flag'), hit.end('flag'), hit['load'])])


_LIST = re.compile(
    r'''lui \$v0, %hi\((?P<sym>\w+) \+ (?P<global>\d+)\)
lw \$v0, %lo\((?P=sym) \+ (?P=global)\)\(\$v0\)
lw \$v0, (?P<head>\d+)\(\$v0\)
lw \$v1, 0\(\$v0\)
beqz \$v1, @17
addu \$a1, \$zero, \$zero
andi \$a0, \$a0, 255
andi \$v0, \$a1, 255
bne \$v0, \$a0, @14
nop
lw \$v0, (?P<flags>\d+)\(\$v1\)
ori \$v0, \$v0, (?P<bit>\d+)
j @17
sw \$v0, (?P=flags)\(\$v1\)
lw \$v1, (?P<next>\d+)\(\$v1\)
bnez \$v1, @7
addiu \$a1, \$a1, 1
jr \$ra
nop''')
_RECORD = '''andi $a1, $a1, 65535
sll $v0, $a1, 2
lw $v1, 16($a0)
addu $v0, $v0, $a1
sll $v0, $v0, 2
addu $t1, $v1, $v0
lbu $v0, 15($t1)
lw $a1, 4($t1)
beqz $v0, @25
addu $t0, $zero, $zero
addiu $a0, $a1, 8
lw $v0, 0($a1)
bnel $v0, $a2, @19
addiu $t0, $t0, 1
lb $v0, -4($a0)
bnel $v0, $zero, @19
addiu $t0, $t0, 1
j @25
sw $a3, 0($a0)
addiu $a0, $a0, 12
lbu $v1, 15($t1)
andi $v0, $t0, 65535
sltu $v0, $v0, $v1
bnez $v0, @11
addiu $a1, $a1, 12
jr $ra
nop'''


def _trace(asm, size):
    lines, labels = _instructions(asm)
    if len(lines) != size:
        return ''
    result = []
    for line in normalized_integer_lines(lines):
        if line.startswith(('beqz ', 'bne ', 'bnez ', 'bnel ', 'j ')):
            label = line.split()[-1]
            if label not in labels:
                return ''
            line = line[:-len(label)] + f'@{labels[label]}'
        result.append(line)
    return '\n'.join(result)


def _masked_list(part, name, rows, asm, end):
    if not any(mark == 'i' and target.startswith('bnez ') for mark, target, _ in rows):
        return None
    target = _LIST.fullmatch(_trace(asm, 19))
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    if not target or not sig:
        return None
    incoming = sig[1]
    body = part.clean[part.opening + 1:end - 1]
    body = re.sub(rf'(?P<label>__repair_rows):\s*\{{\s*do\s*\{{\s*do\s*\{{\s*({IDENT})\s*\+= 1;'
                  r'\s*\} while \(0\);\s*\} while \(0\);\s*\}\s*if \(0\) goto (?P=label);', r'\2 += 1;', body)
    prefix = re.compile(
        rf's32 (?P<i>{IDENT}); void \*(?P<node>{IDENT}); '
        rf'(?P=node) = \*M2C_FIELD\(M2C_FIELD\(&{target["sym"]}, void \*\*, (?P<global>{NUMBER})\), '
        rf'void \*\*\*, (?P<head>{NUMBER})\); (?P=i) = 0; if \((?P=node) != NULL\) \{{ (?P<label>{IDENT}): '
        rf'if \(\(\s*(?P=i) & 0xFF\) == \({incoming} & 0xFF\)\) \{{ '
        rf'M2C_FIELD\((?P=node), s32 \*, (?P<flags>{NUMBER})\) = \(s32\) '
        rf'\(M2C_FIELD\((?P=node), s32 \*, (?P=flags)\) \| (?P<bit>{NUMBER})\); return; \}} '
        rf'(?P=node) = M2C_FIELD\((?P=node), void \*\*, (?P<next>{NUMBER})\); (?P=i) \+= 1; '
        r'(?:if \((?P=node) == NULL\) \{ \} else \{|if \((?P=node) != NULL\) \{) goto (?P=label); \} \}')
    found = prefix.fullmatch(' '.join(body.split()))
    if not found or any(integer(found[k]) != int(target[k]) for k in ('global', 'head', 'flags', 'next', 'bit')):
        return None
    i, node, dest = (found[k] for k in ('i', 'node', 'label'))
    rewritten = f'''
    s32 __repair_cursor_key;
    s32 {i};
    void *{node};
    {node} = *M2C_FIELD(M2C_FIELD(&{target['sym']}, void **, {found['global']}), void ***, {found['head']});
    {i} = 0;
    if ({node} != NULL) {{
        __repair_cursor_key = {incoming} & 0xFF;
{dest}:
        if (({i} & 0xFF) == __repair_cursor_key) {{
            M2C_FIELD({node}, s32 *, {found['flags']}) = (s32) (M2C_FIELD({node}, s32 *, {found['flags']}) | {found['bit']});
            return;
        }}
        {node} = M2C_FIELD({node}, void **, {found['next']});
        {i} += 1;
        if ({node} != NULL) {{
            goto {dest};
        }}
    }}
'''
    return edit(part.source, [(part.opening + 1, end - 1, rewritten)])


_RECORD_SOURCE = _shape('''
    char *@rec; s32 @index; void *@entry; void *@value;
    @entry = M2C_FIELD(@base, s32 *, 0x10) + ((@page & 0xFFFF) * 0x14);
    @rec = M2C_FIELD(@entry, s32 **, 4);
    @index = 0;
    if (M2C_FIELD(@entry, u8 *, 0xF) != 0) {
    @value = (void *)(@rec); @value = (void *)((char *)@value + (s32)(8));
    @loop:
    if (*(s32 *)@rec != @key) { @index += 1; goto @advance; }
    if (M2C_FIELD(@value, s8 *, -4) == 0) {
    M2C_FIELD(@value, s32 *, 0) = @new;
    } else { @index += 1; @advance:
    @rec += 0xC; @value += 0xC;
    if ((u32) (@index & 0xFFFF) >= (u8) M2C_FIELD(@entry, u8 *, 0xF)) {
    } else { goto @loop; } } }
''')


def _record_cursor(part, name, rows, asm, end):
    if any(mark != 'r' for mark, _, _ in rows if mark != ' '):
        return None
    if _trace(asm, 27) != _RECORD:
        return None
    sig = re.search(
        rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT}), s32 ({IDENT}), s32 ({IDENT}), s32 ({IDENT})\)\s*$',
        part.clean[:part.opening])
    if not sig:
        return None
    draft = _RECORD_SOURCE.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    if not draft or tuple(draft[role] for role in ('base', 'page', 'key', 'new')) != sig.groups():
        return None
    base, page, key, new = sig.groups()
    body = f'''
    s8 *__repair_cursor_entry;
    s8 *__repair_cursor_record;
    s8 *__repair_cursor_value;
    s32 __repair_cursor_index;
    s32 __repair_cursor_key = {key};
    __repair_cursor_entry = (s8 *)(*((s32 *)((char *){base} + 0x10)) + (({page} & 65535) * 20));
    __repair_cursor_record = *((s8 **)((char *)__repair_cursor_entry + 4));
    __repair_cursor_index = 0;
    if ((*(u8 *)(__repair_cursor_entry + 15)) == 0) goto __repair_cursor_done;
    __repair_cursor_value = __repair_cursor_record + 8;
__repair_cursor_scan:
    if (*(s32 *)__repair_cursor_record == __repair_cursor_key) goto __repair_cursor_check;
    __repair_cursor_index += 1;
    goto __repair_cursor_advance;
__repair_cursor_check:
    if ((*(s8 *)(__repair_cursor_value - 4)) == 0) goto __repair_cursor_write;
    __repair_cursor_index += 1;
    goto __repair_cursor_advance;
__repair_cursor_write:
    *(s32 *)__repair_cursor_value = {new};
    return;
__repair_cursor_advance:
    __repair_cursor_value += 12;
    __repair_cursor_record += 12;
    if ((u32)(__repair_cursor_index & 65535) < (u8)(*(u8 *)(__repair_cursor_entry + 15))) goto __repair_cursor_scan;
__repair_cursor_done:
    return;
'''
    return edit(part.source, [(part.opening + 1, end - 1, body)])
