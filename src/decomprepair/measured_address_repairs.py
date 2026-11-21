"""Address edits backed by a paired MIPS relocation, add, or store mismatch."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, calls, edit, integer, view
from .kmc_operand_repairs import ADDU
from .pattern_repairs import close
from .target_constant_repairs import LITERAL

REG = r'\$\w+'
DATA = r'D_[0-9A-Fa-f]{8}'
REFERENCE = rf'{IDENT}(?:[+-]0x[0-9a-fA-F]+)?'
HIGH = re.compile(rf'lui\s+({REG}),\s*%hi\(({REFERENCE})\)')
LOW = re.compile(rf'addiu\s+({REG}),\s*({REG}),\s*%lo\(({REFERENCE})\)')
EXTERN = re.compile(rf'\bextern\s+(?P<type>{IDENT}(?:[ \t]+{IDENT})*)[ \t]+'
                    rf'(?P<name>{DATA})\s*(?P<array>\[\s*\])?\s*;')
STORE = re.compile(rf'sw\s+({REG}),\s*(-?(?:0x[0-9a-f]+|\d+))?\(({REG})\)')


def address(reference, symbols):
    match = re.fullmatch(rf'({IDENT})([+-]0x[0-9a-fA-F]+)?', reference)
    base = symbols.resolve(match[1])
    return base + int(match[2] or '0', 0) if base is not None else None


def relocation_pairs(changes, symbols):
    if not 2 <= len(changes) <= 6 or len(changes) % 2:
        return None
    pairs = set()
    for high, low in zip(changes[::2], changes[1::2]):
        i, hi_marker, left, right = high
        j, lo_marker, left_lo, right_lo = low
        if j != i+1 or hi_marker != 'i' or lo_marker != 'i':
            return None
        h, old_h = HIGH.fullmatch(left), HIGH.fullmatch(right)
        l, old_l = LOW.fullmatch(left_lo), LOW.fullmatch(right_lo)
        if (not all((h, old_h, l, old_l)) or not re.fullmatch(DATA,h[2])
                or (h[1], h[1], h[2]) != l.groups()
                or (old_h[1], old_h[1], old_h[2]) != old_l.groups() or h[1] != old_h[1]):
            return None
        target = symbols.by_name.get(h[2])
        old_address = address(old_h[2], symbols)
        if (target is None or target.kind not in ('data','bss') or old_address is None
                or old_address == target.address):
            return None
        pairs.add((old_address,h[2]))
    return next(iter(pairs)) if len(pairs) == 1 else None


def relocation_binding(source, header, part, rows, changes, symbols):
    if symbols is None or not (pair := relocation_pairs(changes,symbols)):
        return None
    old_address, target = pair
    # A remaining matched load/address of this object makes a blanket rename ambiguous.
    for marker, _, candidate in rows:
        refs = re.findall(rf'%(?:hi|lo)\(({REFERENCE})\)',candidate)
        if marker == ' ' and any(address(ref,symbols) == old_address for ref in refs):
            return None
    declarations = [decl for decl in EXTERN.finditer(part.clean,0,part.opening)
                    if symbols.resolve(decl['name']) == old_address
                    and re.search(rf'\b{decl["name"]}\b',part.body)]
    if len(declarations) != 1:
        return None
    decl = declarations[0]
    old = decl['name']
    old_token = rf'\b{old}\b'
    if (re.search(r'\b(?:const|volatile)\b',decl['type'])
            or re.search(old_token,_blank(header))
            or re.search(rf'\b{target}\b',part.clean+'\n'+_blank(header))
            or len(re.findall(old_token,part.clean)) != len(re.findall(old_token,part.body))+1
            or re.search(rf'\b{old}\s*(?:=(?!=)|\+\+|--|\s*\+=|\s*-=)',part.body)):
        return None
    uses = list(re.finditer(old_token,part.body))
    if not decl['array'] and any(not re.search(r'&\s*$',part.body[max(0,use.start()-12):use.start()]) for use in uses):
        return None
    return edit(source,[(decl.start('name'),decl.end('name'),target),
                        *((part.opening+1+use.start(),part.opening+1+use.end(),target) for use in uses)])


def address_add(source, part, left, right):
    a,b = ADDU.fullmatch(left),ADDU.fullmatch(right)
    if not a or not b or a[2] == a[3] or a.groups() != (b[1],b[3],b[2]):
        return []
    result = []
    # A word global supplying a raw base can commute with a side-effect-free scaled local.
    raw = re.compile(rf'\(\s*(?:u8|s8|u16|s16|u32|s32)\s*\*\s*\)\s*\(\s*'
                     rf'(?P<sum>(?P<base>{DATA})\s*\+\s*(?P<index>{IDENT})\s*\*\s*(?P<step>{LITERAL.pattern}))\s*\)')
    for hit in raw.finditer(part.clean,part.opening+1,part.end):
        if (integer(hit['step']) in (2,4,8,16,32)
                and re.search(rf'\bextern\s+(?:s32|u32|int)\s+{hit["base"]}\s*;',part.clean[:part.opening])
                and re.search(rf'\b(?:s32|u32|s16|u16|int)\s+{hit["index"]}\s*;',part.body)):
            result.append(edit(source,[(*hit.span('sum'),f'{hit["index"]} * {hit["step"]} + {hit["base"]}')]))
    # The source already forms byte offsets, so exposing the add as integer
    # arithmetic preserves the byte scaling while letting KMC change operand order.
    byte = re.compile(rf'\breturn\s+(?P<sum>(?P<base>{IDENT})\s*\+\s*'
                      rf'(?P<offset>\(\s*{IDENT}\s*<<\s*[1-5]\s*\)))\s*;')
    if re.search(rf'\bvoid\s*\*\s*{IDENT}\s*\([^;{{}}]*\)\s*$',part.clean[:part.opening]):
        for hit in byte.finditer(part.clean,part.opening+1,part.end):
            if re.search(rf'\b(?:u8|s8|char)\s*\*\s*{hit["base"]}\s*=',part.body):
                result.append(edit(source,[(*hit.span('sum'),f'(void *)({hit["offset"]} + (unsigned int){hit["base"]})')]))
    index = re.compile(rf'&\s*(?P<base>{IDENT})\s*\[\s*(?P<index>\(\s*(?:u8|s8|u16|s16)\s*\)\s*{IDENT})\s*\]')
    for hit in index.finditer(part.clean,part.opening+1,part.end):
        declarations = list(re.finditer(rf'\b({IDENT})\s*\*\s*\*\s*{hit["base"]}\s*=',part.body))
        if len(declarations) == 1:
            replacement = (f'({declarations[0][1]} **)(((unsigned int){hit["index"]} * sizeof(*{hit["base"]})) '
                           f'+ (unsigned int){hit["base"]})')
            result.append(edit(source,[(*hit.span(),replacement)]))
    return list(dict.fromkeys(result))[:3]


def _masked_loop_address(part, rows, change):
    """Expose a masked pointer offset as a word add when only its operands differ."""
    i, _, left, right = change
    target, candidate = map(ADDU.fullmatch, (left, right))
    if i < 2 or not target or not candidate or target[2] == target[3]:
        return None
    dest, offset, base = target.groups()
    if candidate.groups() != (dest, base, offset):
        return None
    mask, shift = rows[i - 2:i]
    if any(mark != ' ' or a != b for mark, a, b in (mask, shift)):
        return None
    index_reg = re.escape(offset)
    bound = re.fullmatch(rf'andi {index_reg}, {REG}, ({NUMBER})', mask[1])
    scale = re.fullmatch(rf'sll {index_reg}, {index_reg}, ([1-5])', shift[1])
    if not bound or integer(bound[1]) not in (255, 65535) or not scale:
        return None
    edits = []
    for hit in re.finditer(
        rf'\b(?P<dst>{IDENT})\s*=\s*(?P<sum>(?P<byteoffset>\(\({IDENT} & (?P<mask>{NUMBER})\) '
        rf'\* (?P<step>{NUMBER})\)) \+ (?P<base>{IDENT}))\s*;', part.body
    ):
        if integer(hit['mask']) != integer(bound[1]) or integer(hit['step']) != 1 << int(scale[1]):
            continue
        if not re.search(rf'\bvoid\s*\*\s*{hit["base"]}\s*(?=[,)])', part.clean[:part.opening]):
            continue
        if not re.search(rf'\bvoid\s*\*\s*{hit["dst"]}\s*;', part.body[:hit.start()]):
            continue
        if re.search(rf'\b{IDENT}[\s*]+{hit["base"]}\s*(?=[=;,)\[])', part.body):
            continue
        start, end = hit.span('sum')
        offset = part.opening + 1
        if part.source[offset + start:offset + end] == hit['sum']:
            replacement = f'(void *)({hit["byteoffset"]} + (u32){hit["base"]})'
            edits.append((offset + start, offset + end, replacement))
    return edit(part.source, edits) if len(edits) == 1 else None


def reciprocal_links(source, part, changes):
    (i,_,left,right),(j,_,left_next,right_next) = changes
    a,b = STORE.fullmatch(left),STORE.fullmatch(left_next)
    if (j != i+1 or (left,left_next) != (right_next,right)
            or not a or not b or a[3] != b[3] or a[2] == b[2]
            or a[3] in ('$sp','$fp','$s8','$gp')):
        return None
    item = rf'(?P<array>{IDENT})\s*\[\s*(?P<index>{IDENT})\s*\]'
    previous = r'(?P=array)\s*\[\s*(?P=index)\s*-\s*1\s*\]'
    current = r'(?P=array)\s*\[\s*(?P=index)\s*\]'
    pattern = re.compile(rf'(?P<prev>\b{item}\s*\.\s*prev\s*=\s*&\s*{previous}\s*;)'
                         rf'(?P<gap>\s*)(?P<next>{previous}\s*\.\s*next\s*=\s*&\s*{current}\s*;)')
    sites = list(pattern.finditer(part.clean,part.opening+1,part.end))
    if len(sites) != 1:
        return None
    hit = sites[0]
    # Keep comments and line placement untouched when the pair is not plain.
    if re.search(r'/[*/]',source[slice(*hit.span())]):
        return None
    return edit(source,[(*hit.span(),source[slice(*hit.span('next'))]+hit['gap']+source[slice(*hit.span('prev'))])])


def _saved_global_call_offset(part, header, rows, change):
    """Recover byte units for an argument formed from a saved global address."""
    i, _, left, right = change
    step = re.compile(rf'addiu \$a0, (?P<reg>\$s[0-7]), (?P<off>-?{NUMBER})')
    want, have = map(step.fullmatch, (left, right))
    if i < 3 or not want or not have or want['reg'] != have['reg']:
        return None
    target, candidate = (integer(match['off'].lstrip('-')) * (-1 if match['off'].startswith('-') else 1)
                         for match in (want, have))
    if not target or candidate != 4 * target:
        return None
    marker, target_call, candidate_call = rows[i - 1]
    callee = re.fullmatch(rf'jal ({IDENT})', target_call)
    if marker != ' ' or not callee or target_call != candidate_call:
        return None
    register = re.escape(want['reg'])
    binding = re.compile(rf'addiu {register}, {register}, %lo\((?P<base>{IDENT})\)')
    for j in range(i - 2, max(0, i - 12), -1):
        op = rows[j][1]
        if anchor := binding.fullmatch(op):
            base = anchor['base']
            high = f'lui {want["reg"]}, %hi({base})'
            if tuple(rows[j - 1]) != (' ', high, high) or tuple(rows[j]) != (' ', op, op):
                return None
            break
        if re.match(rf'(?:b\w*|j|jr|jalr)\s|\w+ {register},', op):
            return None
    else:
        return None
    if (not re.search(rf'\bextern\s+M2C_UNK\s+{base}\s*;', part.clean[:part.opening])
            or re.search(rf'\b{base}\b', _blank(header))
            or re.search(rf'\b{IDENT}[\s*]+{base}\s*(?=[=;,)\[])', part.clean[part.opening:part.end])):
        return None
    matches = []
    for start, end in calls(part, callee[1]):
        actual = part.clean[start:end]
        expr = re.fullmatch(rf'\s*(?P<base>&\s*{base})\s*(?P<sign>[+-])\s*(?P<offset>{NUMBER})\s*', actual)
        if not expr or part.source[start:end] != actual:
            continue
        offset = integer(expr['offset'])
        if (offset if expr['sign'] == '+' else -offset) == target:
            at = start + expr.start('base')
            matches.append((at, at, '(u8 *)'))
    return edit(part.source, matches) if len(matches) == 1 else None


def _copy_cursor_address(part, rows, change):
    """Use integer byte units for a measured destination address in a halfword copy."""
    i, _, wanted, current = change
    a, b = map(ADDU.fullmatch, (wanted, current))
    if i < 2 or i + 3 >= len(rows) or not a or not b:
        return None
    dest, index, base = a.groups()
    if index != dest or base == dest or b.groups() != (dest, base, index):
        return None
    shift = re.fullmatch(rf'sll {re.escape(index)}, \$a1, 1', rows[i - 1][1])
    if not shift or rows[i - 1][1] != rows[i - 1][2]:
        return None
    offsets = []
    for load_i, store_i in ((i - 2, i + 1), (i + 2, i + 3)):
        load, store = rows[load_i][1], rows[store_i][1]
        if load != rows[load_i][2] or store != rows[store_i][2]:
            return None
        read = re.fullmatch(rf'lhu ({REG}), ({NUMBER})?\({re.escape(base)}\)', load)
        write = re.fullmatch(rf'sh ({REG}), ({NUMBER})?\({re.escape(dest)}\)', store)
        if not read or not write or read[1] != write[1]:
            return None
        if integer(read[2] or '0') != integer(write[2] or '0'):
            return None
        offsets.append(integer(read[2] or '0'))
    signature = re.search(rf'\bvoid\s*\*\s*(?P<base>{IDENT})\s*,\s*s32\s+(?P<index>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    base, index = signature['base'], signature['index']
    pattern = re.compile(rf'\b(?P<cursor>{IDENT}) = (?P<sum>\({index} \* 2\) \+ {base});')
    hits = []
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        cursor = hit['cursor']
        if not re.search(rf'\bvoid\s*\*\s*{cursor}\s*;', part.body):
            continue
        field = re.compile(rf'M2C_FIELD\({cursor}, u16 \*, ({NUMBER})\) = '
                           rf'(?:\(u16\) )?M2C_FIELD\({base}, u16 \*, \1\);')
        copied = {integer(m[1]) for m in field.finditer(part.clean, hit.end(), part.end)}
        if set(offsets) <= copied:
            hits.append((*hit.span('sum'), f'(void *)({index} * 2 + (u32){base})'))
    return edit(part.source, hits) if len(hits) == 1 else None


def variants(source, name, header, rows, symbols=None):
    changes = [(i,marker,left,right) for i,(marker,left,right) in enumerate(rows) if marker != ' ']
    if (not 1 <= len(changes) <= 6 or not (part := view(source,name))
            or re.search(r'\b(?:volatile|asm|__asm__)\b',part.body)):
        return []
    if len(changes) == 1:
        if candidate := _saved_global_call_offset(part, header, rows, changes[0]):
            return [('measured_saved_global_call_offset', candidate)]
        if candidate := _copy_cursor_address(part, rows, changes[0]):
            return [('measured_copy_cursor_address', candidate)]
        if candidate := _masked_loop_address(part, rows, changes[0]):
            return [('measured_masked_loop_address', candidate)]
        _,_,left,right = changes[0]
        return [('measured_address_add',candidate) for candidate in address_add(source,part,left,right)]
    if candidate := relocation_binding(source,header,part,rows,changes,symbols):
        return [('measured_relocation_binding',candidate)]
    if len(changes) == 2 and (candidate := reciprocal_links(source,part,changes)):
        return [('measured_link_store_order',candidate)]
    return []


# The low half can occupy the call delay slot for an address argument.
_OFFSET_HIGH = re.compile(rf'lui (?P<reg>{REG}), %hi\((?P<base>{IDENT}) \+ (?P<off>{NUMBER})\)')
_OFFSET_LOW = re.compile(
    rf'addiu (?P<reg>{REG}), (?P=reg), %lo\((?P<base>{IDENT}) \+ '
    rf'(?:(?P<plain>{NUMBER})|\((?P<masked>{NUMBER}) & 0xFFFF\))\)'
)
_BYTE_ADDR = re.compile(rf'&\s*(?P<base>{IDENT})\s*\+\s*(?P<off>{NUMBER})\b(?!\s*[*%/])')
_SECOND_ARG = re.compile(
    rf'addiu \$sp, \$sp, -(?P<frame>{NUMBER})\nsw \$ra, (?P<slot>{NUMBER})\(\$sp\)\n'
    rf'lui \$a1, [^\n]+\njal (?P<callee>{IDENT})\naddiu \$a1, \$a1, [^\n]+\n'
    r'lw \$ra, (?P=slot)\(\$sp\)\n(?:addu \$v0, \$zero, \$zero|move \$v0, \$zero)\n'
    r'jr \$ra\naddiu \$sp, \$sp, (?P=frame)'
)


def _offset_pairs(asm):
    if '%hi(' not in asm or '%lo(' not in asm or ' + ' not in asm:
        return [], set()
    from .measured_stack_drafts import _lines

    lines = [' '.join(line.split()) for line in _lines(asm) if not line.startswith(('glabel ', 'endlabel '))]
    pairs = set()
    for i, line in enumerate(lines[:-1]):
        high = _OFFSET_HIGH.fullmatch(line)
        if not high:
            continue
        second = i + 2 if lines[i + 1].startswith('jal ') else i + 1
        low = _OFFSET_LOW.fullmatch(lines[second]) if second < len(lines) else None
        if (low and (high['reg'], high['base']) == (low['reg'], low['base'])
                and integer(high['off']) == integer(low['plain'] or low['masked'])):
            pairs.add((high['reg'], high['base'], integer(high['off'])))
    return lines, pairs


def _indexed_word_pairs(lines):
    pairs = set()
    for i, line in enumerate(lines[:-2]):
        top = _OFFSET_HIGH.fullmatch(line)
        if not top:
            continue
        base = re.escape(top['reg'])
        add = re.fullmatch(rf'addu {base}, {base}, (?P<index>\$\w+)', lines[i + 1])
        bottom = re.fullmatch(
            rf'lw {REG}, %lo\(({IDENT}) \+ (?:(?P<plain>{NUMBER})|\((?P<masked>{NUMBER}) & 0xFFFF\))\)\({base}\)',
            lines[i + 2])
        if (not add or not bottom or add['index'] == top['reg'] or top['base'] != bottom[1]
                or integer(top['off']) != integer(bottom['plain'] or bottom['masked'])):
            continue
        index = re.escape(add['index'])
        # The index must still hold a word-scaled value at the address add.
        for previous in reversed(lines[max(0, i - 12):i]):
            if re.match(r'^(?:[bj]\w*\s|\.L)', previous):
                break
            if re.match(rf'\w+ {index},', previous):
                if re.fullmatch(rf'sll {index}, {index}, (?:2|0x2)', previous):
                    pairs.add((top['base'], integer(top['off'])))
                break
    return pairs


def _indexed_word_offset(part, header, pairs):
    hits = []
    for deref in re.compile(r'\*\(&(?P<base>'+IDENT+r') \+ (?P<off>'+NUMBER+r') \+ \(').finditer(
            part.clean, part.opening + 1, part.end):
        base, offset = deref['base'], integer(deref['off'])
        if (base, offset) not in pairs or not re.search(rf'\bextern\s+M2C_UNK\s+{base}\s*;', part.clean[:part.opening]):
            continue
        if re.search(rf'\b{base}\b', _blank(header)):
            continue
        index_close = close(part.clean, deref.end() - 1)
        if not index_close or part.clean[index_close:index_close + 1] != ')':
            continue
        if (not re.search(r' \* (?:4|0x4)\)$', part.clean[deref.end():index_close])
                or re.match(r'\s*(?:=(?!=)|[-+*/%&|^]=|\+\+|--)', part.clean[index_close + 1:])):
            continue
        hits.append((*deref.span(), f"*(s32 *)((char *)&{base} + {deref['off']} + ("))
    return edit(part.source, hits) if len(hits) == 1 else None


def byte_offsets_apply(asm):
    lines, pairs = _offset_pairs(asm)
    return bool(pairs or _indexed_word_pairs(lines))


def _wrapper_offset(source, part, name, header, target, hit, replacement):
    """Also restore the incoming first argument for an otherwise empty wrapper."""
    callee = target['callee']
    context = _blank(header)
    if (re.search(rf'\b{callee}\b|(?m:^[ \t]*#\s*define\s+arg0\b)', context)
            or re.search(r'\barg0\b', part.clean)):
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*(?P<params>void)\s*\)\s*$', part.clean[:part.opening])
    body = part.clean[part.opening + 1:part.clean.rfind('}', part.opening, part.end)]
    statements = re.fullmatch(rf'\s*{callee}\(\s*{re.escape(hit[0])}\s*\);\s*return 0;\s*', body)
    prototype = list(re.finditer(
        rf'(?m)^[ \t]*M2C_UNK {callee}\((?P<arg>void \*)\);[ \t]*/\* extern \*/[ \t]*$',
        source[:part.opening]))
    if not signature or not statements or len(prototype) != 1 or len(re.findall(rf'\b{callee}\s*\(', part.clean)) != 2:
        return None
    at = prototype[0].start('arg')
    return edit(source, [(at, at, 's32, '), (*signature.span('params'), 's32 arg0'),
                         (*hit.span(), f'arg0, {replacement}')])


def rewrite_byte_offsets(source, name, asm, header=''):
    """Treat an evidenced displacement from a generated global as bytes."""
    if 'M2C_UNK' not in source or '&' not in source:
        return None
    lines, pairs = _offset_pairs(asm)
    if not lines or not (part := view(source, name)):
        return None
    if re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return None

    if indexed := _indexed_word_pairs(lines):
        if candidate := _indexed_word_offset(part, header, indexed):
            return candidate
    edits = []
    wrapper = _SECOND_ARG.fullmatch('\n'.join(lines)) if len(lines) == 9 else None
    for hit in _BYTE_ADDR.finditer(part.clean, part.opening + 1, part.end):
        base, off = hit['base'], integer(hit['off'])
        regs = {reg for reg, symbol, offset in pairs if (symbol, offset) == (base, off)}
        if (not regs or not re.search(rf'\bextern\s+M2C_UNK\s+{base}\s*;', part.clean[:part.opening])
                or re.search(rf'\b{base}\b', _blank(header)) or re.search(r'/[*/]', source[slice(*hit.span())])):
            continue
        # Do not touch an already cast address or a local shadow of the global.
        if (part.clean[:hit.start()].rstrip().endswith(')') or re.search(
                rf'\b{IDENT}[\s*]+{base}\s*(?=[=;,)\[])', part.clean[part.clean.rfind(name, 0, part.opening):part.end])):
            continue
        replacement = f"(char *)&{base} + {hit['off']}"
        if wrapper and regs == {'$a1'}:
            return _wrapper_offset(source, part, name, header, wrapper, hit, replacement)
        edits.append((*hit.span(), replacement))
    return edit(source, edits) if 0 < len(edits) <= 4 else None
