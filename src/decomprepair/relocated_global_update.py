"""Recover a standalone word when m2c turns a relocated update into a field."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names
from .mips_addresses import resolved
from .sdk_io_repairs import instructions
from .target_call_arity_repairs import _instructions
from .target_memory_repairs import _statement

TARGET = re.compile(
    rf'lui \$v0, %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\n'
    r'lw \$v0, %lo\((?P=base)(?(offset) \+ (?P=offset))\)\(\$v0\)\n'
    rf'lui \$v1, \((?P<multiplier>{NUMBER}) >> 16\)\n'
    r'ori \$v1, \$v1, \((?P=multiplier) & 0xFFFF\)\n'
    r'mult \$v0, \$v1\nmflo \$v0\n'
    rf'addiu \$v1, \$v0, (?P<increment>{NUMBER})\n'
    rf'addiu \$v0, \$v0, (?P<result>{NUMBER})\n'
    rf'sra \$v0, \$v0, (?P<shift>{NUMBER})\n'
    r'lui \$at, %hi\((?P=base)(?(offset) \+ (?P=offset))\)\n'
    r'sw \$v1, %lo\((?P=base)(?(offset) \+ (?P=offset))\)\(\$at\)\n'
    rf'jr \$ra\nandi \$v0, \$v0, (?P<mask>{NUMBER})'
)

DRAFT = re.compile(
    rf'\s*s32 (?P<product>{IDENT});\s*'
    rf'(?P=product) = (?P<read>M2C_FIELD\(&(?P<base>{IDENT}), s32 \*, (?P<offset>{NUMBER})\))'
    rf' \* (?P<multiplier>{NUMBER});\s*'
    rf'(?P<write>(?P=read)) = \(s32\) \((?P=product) \+ (?P<increment>{NUMBER})\);\s*'
    rf'return \(\(s32\) \((?P=product) \+ (?P<result>{NUMBER})\) >> (?P<shift>{NUMBER})\)'
    rf' & (?P<mask>{NUMBER});\s*'
)


def _target(asm):
    if 'mflo' not in asm or 'andi' not in asm or '%hi(' not in asm:
        return None
    lines = (f'{op} {" ".join(args.split())}' for op, args in _instructions(abi_register_names(asm)))
    return TARGET.fullmatch('\n'.join(lines))


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header='', resolve=None):
    """Use a typed alias for the word read and written by the original function."""
    if resolve is None or 'M2C_FIELD' not in source or not (target := _target(asm)):
        return None
    part = view(source, name)
    if not part or not re.search(rf'\bs32\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening]):
        return None
    start = part.opening + 1
    stop = part.clean.rfind('}', start, part.end)
    draft = DRAFT.fullmatch(part.clean, start, stop)
    if not draft or any(integer(draft[field]) != integer(target[field])
                        for field in ('multiplier', 'increment', 'result', 'shift', 'mask')):
        return None
    bases = [resolve(binding['base']) for binding in (target, draft)]
    if None in bases:
        return None
    address = bases[0] + integer(target['offset'] or '0')
    if address != bases[1] + integer(draft['offset']) or not 0 <= address <= 0xFFFFFFFF or address % 4:
        return None
    words = instructions(asm)
    if len(words) != 13:
        return None
    addresses = resolved(b''.join(word.to_bytes(4, 'big') for word in words))
    # The two relocations must resolve in the words at the actual load and store.
    if (addresses.get(4), addresses.get(40)) != (address, address):
        return None
    return _direct_word(source, name, header, resolve, address, [draft.span('read'), draft.span('write')])


COUNTDOWN = re.compile(
    rf'(?m)^lui \$v0, %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\n'
    r'lw \$v0, %lo\((?P=base)(?(offset) \+ (?P=offset))\)\(\$v0\)\n'
    rf'blez \$v0, (?P<nonpositive>\.L\w+)\nnop\naddiu \$v0, \$v0, -(?:1|0x1)\n'
    r'lui \$at, %hi\((?P=base)(?(offset) \+ (?P=offset))\)\n'
    r'j (?P<exit>\.L\w+)\nsw \$v0, %lo\((?P=base)(?(offset) \+ (?P=offset))\)\(\$at\)\n'
    r'(?P=nonpositive):\nbnez \$v0, (?P<skip>\.L\w+)\naddiu \$v0, \$zero, -(?:1|0x1)\n'
    rf'lui \$v1, %hi\((?P<obj>{IDENT})(?: \+ (?P<objoff>{NUMBER}))?\)\n'
    r'lw \$v1, %lo\((?P=obj)(?(objoff) \+ (?P=objoff))\)\(\$v1\)\n'
    r'lui \$at, %hi\((?P=base)(?(offset) \+ (?P=offset))\)\n'
    r'sw \$v0, %lo\((?P=base)(?(offset) \+ (?P=offset))\)\(\$at\)\n'
    rf'sh \$zero, (?P<clear>{NUMBER})\(\$v1\)\n(?P=skip):'
)

COUNTDOWN_DRAFT = re.compile(
    rf'\s*if \((?P<field>M2C_FIELD\(&(?P<base>{IDENT}), s32 \*, (?P<offset>{NUMBER})\)) > 0\) {{\s*'
    r'(?P=field) = \(s32\) \((?P=field) - 1\);\s*return;\s*}\s*'
    r'if \((?P=field) == 0\) {\s*(?P=field) = -1;\s*'
    rf'M2C_FIELD\(M2C_FIELD\(&(?P<obj>{IDENT}), void \*\*, (?P<objoff>{NUMBER})\), s16 \*, '
    rf'(?P<clear>{NUMBER})\) = 0;\s*}}'
)


def _countdown_target(asm):
    if 'blez' not in asm or '%hi(' not in asm:
        return None
    from .measured_stack_drafts import _lines

    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    match = COUNTDOWN.match(lines)
    if not match or len({match[key] for key in ('nonpositive', 'skip', 'exit')}) != 3:
        return None
    if not re.search(rf'(?m)^{re.escape(match["exit"])}:\njr \$ra\nnop$', lines[match.end():]):
        return None
    return match


def countdown_applies(asm):
    return _countdown_target(asm) is not None


def _direct_word(source, name, header, resolve, address, accesses):
    alias = f'D_{address:08X}'
    if (not 0 <= address <= 0xFFFFFFFF or address % 4 or resolve(alias) != address
            or re.search(rf'\b{alias}\b', source + '\n' + header)):
        return None
    definition = find(source, name)[0]
    return edit(source, [(definition, definition, f'extern s32 {alias};\n\n'),
                         *((a, b, alias) for a, b in accesses)])


def rewrite_countdown(source, name, asm, header='', resolve=None):
    """Use direct word accesses in the proven countdown prefix."""
    if resolve is None or 'M2C_FIELD' not in source or not (target := _countdown_target(asm)):
        return None
    part = view(source, name)
    if not part or not re.search(rf'\bvoid\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening]):
        return None
    draft = COUNTDOWN_DRAFT.match(part.clean, part.opening + 1, part.end)
    if not draft or integer(draft['clear']) != integer(target['clear']):
        return None

    def address(binding, key, offset):
        base = resolve(binding[key])
        return None if base is None else base + integer(binding[offset] or '0')

    counter = address(target, 'base', 'offset')
    obj = address(target, 'obj', 'objoff')
    if (counter is None or obj is None or obj == counter or counter != address(draft, 'base', 'offset')
            or obj != address(draft, 'obj', 'objoff')):
        return None
    words = instructions(asm)
    if len(words) < 15:
        return None
    # Decode each load/store pair independently, including the first store in a jump delay slot.
    for high, low, opcode, expected in ((0, 1, 35, counter), (5, 7, 43, counter),
                                       (10, 11, 35, obj), (12, 13, 43, counter)):
        if words[high] >> 26 != 15 or words[low] >> 26 != opcode:
            return None
        pair = words[high].to_bytes(4, 'big') + words[low].to_bytes(4, 'big')
        if resolved(pair).get(4) != expected:
            return None
    accesses = [hit.span() for hit in re.compile(re.escape(draft['field'])).finditer(
        part.clean, draft.start(), draft.end())]
    return _direct_word(source, name, header, resolve, counter, accesses)


RELOAD_WRAPPER = re.compile(
    rf'addiu \$sp, \$sp, -(?P<frame>{NUMBER})\nsw \$s0, (?P<saved>{NUMBER})\(\$sp\)\n'
    r'(?:move \$s0, \$a0|addu \$s0, \$a0, \$zero)\n'
    rf'lui \$a0, %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\n'
    r'lw \$a0, %lo\((?P=base)(?(offset) \+ (?:(?P=offset)|\((?P=offset) & 0xFFFF\)))\)\(\$a0\)\n'
    rf'sw \$ra, (?P<ret>{NUMBER})\(\$sp\)\njal (?P<first>{IDENT})\n'
    rf'addiu \$a1, \$zero, (?P<literal>{NUMBER})\n'
    r'lui \$a1, %hi\((?P=base)(?(offset) \+ (?P=offset))\)\n'
    r'lw \$a1, %lo\((?P=base)(?(offset) \+ (?:(?P=offset)|\((?P=offset) & 0xFFFF\)))\)\(\$a1\)\n'
    rf'jal (?P<second>{IDENT})\n(?:move \$a0, \$s0|addu \$a0, \$s0, \$zero)\n'
    r'lw \$ra, (?P=ret)\(\$sp\)\nlw \$s0, (?P=saved)\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, (?P=frame)',
)


def _reload_target(asm):
    if asm.count('jal') != 2 or '%hi(' not in asm:
        return None
    lines = (f'{op} {" ".join(args.split())}' for op, args in _instructions(abi_register_names(asm)))
    return RELOAD_WRAPPER.fullmatch('\n'.join(lines))


def reload_applies(asm):
    return _reload_target(asm) is not None


def rewrite_reload_wrapper(source, name, asm, header='', resolve=None):
    """Read the same relocated word before each call, with corroborating machine words."""
    if resolve is None or 'M2C_FIELD' not in source or not (target := _reload_target(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*s32\s+(?P<arg>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None

    first, second, arg = target['first'], target['second'], signature['arg']
    field = rf'M2C_FIELD\(&(?P<base>{IDENT}), s32 \*, (?P<offset>{NUMBER})\)'
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    draft = re.compile(rf'\s*{first}\((?P<read>{field}), (?P<literal>{NUMBER})\);\s*'
                       rf'{second}\({arg}, (?P<reload>(?P=read))\);\s*').fullmatch(part.clean, start, end)
    if not draft or integer(draft['literal']) != integer(target['literal']):
        return None
    old, original = (resolve(binding['base']) for binding in (draft, target))
    if old is None or original is None:
        return None
    address = original + integer(target['offset'] or '0')
    if old + integer(draft['offset']) != address:
        return None

    words = instructions(asm)
    if len(words) != 16:
        return None
    addresses = resolved(b''.join(word.to_bytes(4, 'big') for word in words))
    if (addresses.get(16), addresses.get(36)) != (address, address):
        return None
    return _direct_word(source, name, header, resolve, address, [draft.span('read'), draft.span('reload')])


_BRANCH_BYTE = re.compile(
    rf'lui (?P<load>\$\w+), %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\n'
    rf'lbu (?P=load), %lo\((?P=base)(?(offset) \+ (?:\()?(?P=offset)(?: & 0xFFFF\))?)\)\((?P=load)\)\n'
    rf'addiu (?P<compare>\$\w+), \$zero, (?P<value>{NUMBER})\n'
    r'bne (?P=load), (?P=compare), \.L\w+\nnop\n'
    rf'lui (?P<store>\$\w+), %hi\((?P=base)(?(offset) \+ (?P=offset))\)\n'
    r'sb \$zero, %lo\((?P=base)(?(offset) \+ (?:\()?(?P=offset)(?: & 0xFFFF\))?)\)\((?P=store)\)'
)
_BYTE_TEST = re.compile(
    rf'if\s*\(\s*(?P<field>M2C_FIELD\(\s*&(?P<base>{IDENT}),\s*u8\s*\*,\s*(?P<offset>{NUMBER})\s*\))'
    rf'\s*==\s*(?P<value>{NUMBER})\s*\)\s*{{\s*(?P<clear>(?P=field))\s*=\s*0U?\s*;'
)


def _branch_byte_matches(asm):
    from .mips_returns import instructions as instruction_text

    lines = [' '.join(row.split()) for row in instruction_text(abi_register_names(asm))]
    text = '\n'.join(lines)
    for target in _BRANCH_BYTE.finditer(text):
        yield target, text.count('\n', 0, target.start())


def branch_byte_applies(asm):
    return 'lbu' in asm and 'sb ' in asm and next(_branch_byte_matches(asm), None) is not None


def rewrite_branch_byte(source, name, asm, header='', resolve=None):
    """Give a tested and cleared byte its own name when the target materializes it twice."""
    if resolve is None or 'M2C_FIELD' not in source or not branch_byte_applies(asm):
        return None
    part = view(source, name)
    if not part:
        return None
    words = instructions(asm)
    targets = {}
    for target, start in _branch_byte_matches(asm):
        def operand(at, opcode):
            pair = words[at:at+2]
            if len(pair) == 2 and pair[0] >> 26 == 15 and pair[1] >> 26 == opcode:
                return resolved(b''.join(word.to_bytes(4, 'big') for word in pair)).get(4)

        address = operand(start, 36)
        base = resolve(target['base'])
        if (address is not None and address == operand(start+5, 40) and base is not None
                and address == base + integer(target['offset'] or '0')):
            targets.setdefault(address, set()).add(integer(target['value']))
    for draft in _BYTE_TEST.finditer(part.clean, part.opening + 1, part.end):
        base = resolve(draft['base'])
        if base is None or re.search(rf'\bvolatile\b[^;{{}}\n]*\b{draft["base"]}\b', header + part.clean):
            continue
        address = base + integer(draft['offset'])
        if targets.get(address) != {integer(draft['value'])}:
            continue
        alias = f'D_{address:08X}'
        if (not 0 <= address <= 0xFFFFFFFF or resolve(alias) != address
                or re.search(rf'\b{alias}\b', source + '\n' + header)):
            continue
        # Adding a second name must not leave other base-relative uses of this byte behind.
        if len(re.findall(rf'\bM2C_FIELD\(\s*&{draft["base"]}\s*,[^,]+,\s*{draft["offset"]}\s*\)',
                          part.clean)) != 2:
            continue
        definition = find(source, name)[0]
        return edit(source, [(definition, definition, f'extern u8 {alias};\n\n'),
                             (*draft.span('field'), alias), (*draft.span('clear'), alias)])
    return None


INCREMENT_TARGET = re.compile(
    rf'lui (?P<readreg>\$\w+), %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\n'
    r'lw (?P<value>\$\w+), %lo\((?P=base)(?(offset) \+ (?P=offset))\)\((?P=readreg)\)\n'
    rf'addiu (?P=value), (?P=value), (?P<amount>{NUMBER})\n'
    r'lui (?P<storereg>\$\w+), %hi\((?P=base)(?(offset) \+ (?P=offset))\)\n'
    r'sw (?P=value), %lo\((?P=base)(?(offset) \+ (?P=offset))\)\((?P=storereg)\)'
)
INCREMENT_DRAFT = re.compile(
    rf'(?P<field>M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\))'
    rf'\s*=\s*\(\s*s32\s*\)\s*\(\s*(?P<read>(?P=field))\s*\+\s*(?P<amount>{NUMBER})\s*\)\s*;'
)


def rewrite_increment(source, name, asm, header='', resolve=None):
    """Name a relocated word directly when the target increments that exact address."""
    if resolve is None or 'M2C_FIELD' not in source or '%hi(' not in asm:
        return None
    # Do not replace a project-specific macro which can perform additional work.
    definitions = re.findall(r'^\s*#\s*define\s+M2C_FIELD([^\n]*)',header+'\n'+source,re.M)
    if (len(definitions)!=1 or re.sub(r'\s+','',definitions[0]) !=
            '(expr,type_ptr,offset)(*(type_ptr)((s8*)(expr)+(offset)))'
            or re.search(r'^\s*#\s*undef\s+M2C_FIELD\b',header+'\n'+source,re.M)):
        return None
    part = view(source,name)
    if not part:
        return None
    lines = [f'{op} {" ".join(args.split())}' for op,args in _instructions(abi_register_names(asm))]
    words = instructions(asm)
    if len(lines)!=len(words):
        return None
    targets = list(INCREMENT_TARGET.finditer('\n'.join(lines)))
    if len(targets)!=1:
        return None
    target = targets[0]
    index = '\n'.join(lines)[:target.start()].count('\n')
    address = resolve(target['base'])
    if address is None:
        return None
    address += integer(target['offset'] or '0')
    for high,low,opcode in ((index,index+1,35),(index+3,index+4,43)):
        if words[high]>>26!=15 or words[low]>>26!=opcode:
            return None
        pair = words[high].to_bytes(4,'big')+words[low].to_bytes(4,'big')
        if resolved(pair).get(4)!=address:
            return None
    for draft in INCREMENT_DRAFT.finditer(part.clean,part.opening+1,part.end):
        base = resolve(draft['base'])
        if (not _statement(part,draft.start()) or base is None or base+integer(draft['offset'])!=address
                or integer(draft['amount'])!=integer(target['amount'])):
            continue
        return _direct_word(source,name,header,resolve,address,[draft.span('field'),draft.span('read')])
    return None


def rewrite_hoisted_word_read(source, name, rows, asm, header='', resolve=None):
    """Use a direct alias when a target reloads a word instead of its hoisted address."""
    if resolve is None or 'M2C_FIELD' not in source:
        return None
    context = header+'\n'+source
    definitions = re.findall(r'^\s*#\s*define\s+M2C_FIELD([^\n]*)',context,re.M)
    if (len(definitions)!=1 or re.sub(r'\s+','',definitions[0]) !=
            '(expr,type_ptr,offset)(*(type_ptr)((s8*)(expr)+(offset)))' or
            re.search(r'^\s*#\s*undef\s+M2C_FIELD\b',context,re.M)):
        return None
    reg = r'\$[a-z0-9]+'
    direct = re.compile(rf'lw (?P<value>{reg}), %lo\((?P<symbol>{IDENT})\)\((?P<valuebase>{reg})\)')
    indirect = re.compile(rf'lw (?P<value>{reg}), (?:0)?\((?P<base>{reg})\)')
    targets = []
    for mark,left,right in rows:
        a,b = direct.fullmatch(left),indirect.fullmatch(right)
        if mark==' ' or not a or not b or a['value']!=b['value'] or a['valuebase']!=a['value']:
            continue
        symbol = re.escape(a['symbol'])
        scratch = re.escape(b['base'])
        if (not any(re.fullmatch(rf'lui {re.escape(a["value"])}, %hi\({symbol}\)',x) for _,x,_ in rows)
                or not any(re.fullmatch(rf'lui {scratch}, %hi\({symbol}\)',y) for _,_,y in rows)
                or not any(re.fullmatch(rf'addiu {scratch}, {scratch}, %lo\({symbol}\)',y) for _,_,y in rows)):
            continue
        address = resolve(a['symbol'])
        if address is not None:
            targets.append((a['value'],address))
    if len(targets)!=1:
        return None
    value,address = targets[0]
    lines = [f'{op} {" ".join(args.split())}'.strip() for op,args in _instructions(abi_register_names(asm))]
    words = instructions(asm)
    if len(lines)!=len(words):
        return None
    high = re.compile(rf'lui {re.escape(value)}, %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)')
    low = re.compile(rf'lw {re.escape(value)}, %lo\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\({re.escape(value)}\)')
    proven = False
    for i in range(len(lines)-1):
        a,b = high.fullmatch(lines[i]),low.fullmatch(lines[i+1])
        if not a or not b or (a['base'],a['offset'])!=(b['base'],b['offset']):
            continue
        base = resolve(a['base'])
        pair = words[i].to_bytes(4,'big')+words[i+1].to_bytes(4,'big')
        if (base is not None and base+integer(a['offset'] or '0')==address and
                words[i]>>26==15 and words[i+1]>>26==35 and resolved(pair).get(4)==address):
            proven = True
    if not proven or not (part := view(source,name)):
        return None
    field = re.compile(rf'M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)')
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(context),re.M))
    matches = []
    for hit in field.finditer(part.clean,part.opening+1,part.end-1):
        base = resolve(hit['base'])
        if base is not None and hit['base'] not in macros and base+integer(hit['offset'])==address:
            matches.append(hit.span())
    return _direct_word(source,name,header,resolve,address,matches) if len(matches)==1 else None
