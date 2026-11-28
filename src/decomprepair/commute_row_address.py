"""Commute a bounded row offset with a 32-bit MIPS table address.

A KMC O1 state handler used an unsigned byte times a row stride to form a
byte-table pointer. Expressing the address as offset plus the table's 32-bit
address reduced the linked diagnostic from 150 to 145. A later unsigned-loop
offset improved 115 to 110 with the same address form. Allocation remains a
hypothesis; the judge decides whether this form helps another function.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'commute_row_address'
SLOT_FAMILY = 'commute_scoped_slot_address'
PAIRED_FAMILY = 'commute_weighted_slot_address'
LIMIT = 6


def variants(source, name, header='', flags=None):
    flags = flags.split() if isinstance(flags, str) else list(flags or ())
    if ('-mgp32' not in flags or any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@', '-mgp64'))
                                    or (f.startswith('-mabi') and f not in ('-mabi=32', '-mabi=o32')) for f in flags)):
        return []
    context = _blank(source + '\n' + header)
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|class|namespace|template|operator)\b|::', context):
        return []
    if any(integer_abi.scalar(t, context, 'mips') != expected for t, expected in
           (('u8', (8, False)), ('u32', (32, False)), ('s32', (32, True)))):
        return []
    part = view(source, name)
    if not part:
        return []
    clean, body = part.clean, part.body
    if re.search(r'\b(?:volatile|_Atomic)\b', body):
        return []
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if not signatures:
        return []
    signature = clean[signatures[-1].start():part.opening]
    if re.search(rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*)(?:u8|u32|s32)\s*(?=[,)\[])', signature):
        return []
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', context))
    if (re.search(r'\btypedef\b', body) or macros.intersection(re.findall(IDENT, body)) or {'u8', 'u32', 's32'} & macros
            or re.search(rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*)(?:u8|u32|s32)\s*(?=[;=,\[])', body)
            or re.search(r'\b(?:__typeof__|typeof)\s*\([^;{}]*\)\s*\**\s*(?:u8|u32|s32)\s*(?=[;=,\[])', body)):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    pattern = re.compile(
        rf'(?m)^[ \t]*(?P<offset>{IDENT})\s*=\s*(?P<index>{IDENT})\s*\*\s*(?P<stride>0[xX][0-9A-Fa-f]+|[0-9]+)\s*;'
        rf'\s*\n[ \t]*(?P<statement>(?P<row>{IDENT})\s*=\s*(?P<base>{IDENT})\s*\+\s*(?P=offset)\s*;)')
    out = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        offset, index, row, base = (hit[k] for k in ('offset', 'index', 'row', 'base'))
        literal = hit['stride']
        if len(literal) > 1 and literal.startswith('0') and not literal.lower().startswith('0x'):
            continue  # C's leading-zero octal is deliberately not interpreted here.
        if len({offset, index, row, base}) != 4 or int(literal, 0) > 0x7fffffff // 255:
            continue
        if clean[part.opening + 1:hit.start()].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        index_type = 'u8' if re.search(rf'(?m)^[ \t]*u8\s+{re.escape(index)}\s*;', body) else 'u32'
        for var, typ, star in ((offset, 's32', ''), (index, index_type, ''), (row, 'u8', r'\*'), (base, 'u8', r'\*')):
            decls = list(re.finditer(rf'(?m)^[ \t]*{typ}\s*{star}\s*(?P<name>{re.escape(var)})\s*;', body))
            if len(decls) != 1:
                break
            position = part.opening + 1 + decls[0].start('name')
            if any(part.opening < a < position < b for a, b in pairs.items()):
                break
            shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])'
            typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(var)}\s*(?=[;=,\[])'
            if len(re.findall(shadow, body)) != 1 or re.search(typeof_shadow, body):
                break
        else:
            replacement = f'{row} = (u8 *)({offset} + (u32){base});'
            out.append((FAMILY, edit(source, [(hit.start('statement'), hit.end('statement'), replacement)])))
            if len(out) >= LIMIT:
                break
    if len(out) < LIMIT:
        out.extend(_scoped_slots(source, part, pairs)[:LIMIT - len(out)])
    return out


def _unconditional_extern(clean, name, byte_type):
    """Require a visible one-line declaration outside preprocessor branches."""
    pattern = re.compile(rf'^\s*extern\s+{byte_type}\s+{re.escape(name)}\s*\[\s*\]\s*;\s*$')
    depth = 0
    for line in clean.splitlines():
        directive = re.match(r'^\s*#\s*(if|ifdef|ifndef|endif)\b', line)
        if directive:
            depth += -1 if directive[1] == 'endif' else 1
            if depth < 0:
                return False
        elif depth == 0 and pattern.fullmatch(line):
            return True
    return False


def _scoped_slots(source, part, pairs):
    """The promoted index has one byte load; the local table base stays in its block."""
    clean, body = part.clean, part.body
    indices = re.finditer(
        rf'(?m)^[ \t]*__typeof__\s*\(\s*\*\s*(?P<input>{IDENT})\s*\+\s*0\s*\)\s+(?P<index>{IDENT})\s*;',
        clean[part.opening + 1:part.end])
    out = []
    for decl in indices:
        table, index = decl['input'], decl['index']
        pos = part.opening + 1 + decl.start('index')
        if any(part.opening < a < pos < b for a, b in pairs.items()):
            continue
        if (not _unconditional_extern(clean, table, r'unsigned\s+char')
                or len(re.findall(rf'\b{re.escape(table)}\b', clean[:part.opening])) != 1):
            continue
        # Its only assignment is a byte read, and it has one use. No escape,
        # shadow, compound update or path can inject an unbounded value.
        if len(re.findall(rf'\b{re.escape(index)}\b', body)) != 3:
            continue
        if not re.search(rf'\b{re.escape(index)}\s*=\s*\*\s*\(\s*{re.escape(table)}\s*\+[^;]*\)\s*;', body):
            continue
        shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(table)}\s*(?=[;=,\[])'
        typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(table)}\s*(?=[;=,\[])'
        if re.search(shadow, body) or re.search(typeof_shadow, body):
            continue
        assignment = re.compile(rf'(?P<row>{IDENT})\s*=\s*(?P<base>{IDENT})\s*\+\s*\(\s*{re.escape(index)}\s*\*\s*4\s*\)\s*;')
        for hit in assignment.finditer(clean, part.opening + 1, part.end):
            row, base = hit['row'], hit['base']
            if len({row, base, index, table}) != 4:
                continue
            rows = list(re.finditer(rf'(?m)^[ \t]*s32\s*\*\s*(?P<name>{re.escape(row)})\s*;', body))
            if len(rows) != 1:
                continue
            row_pos = part.opening + 1 + rows[0].start('name')
            row_shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(row)}\s*(?=[;=,\[])'
            typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(row)}\s*(?=[;=,\[])'
            if (any(part.opening < a < row_pos < b for a, b in pairs.items())
                    or len(re.findall(row_shadow, body)) != 1 or re.search(typeof_shadow, body)):
                continue
            for a, b in sorted(pairs.items(), key=lambda pair: pair[1] - pair[0]):
                if not a < hit.start() < hit.end() <= b:
                    continue
                block = clean[a + 1:b]
                base_decl = re.search(rf'__typeof__\s*\(\s*(?P<array>{IDENT})\s*\+\s*0\s*\)\s+{re.escape(base)}\s*;', block)
                if not base_decl or a + 1 + base_decl.start() >= hit.start():
                    continue
                array = base_decl['array']
                array_shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(array)}\s*(?=[;=,\[])'
                array_typeof = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(array)}\s*(?=[;=,\[])'
                if (re.search(array_shadow, body) or re.search(array_typeof, body)
                        or len(re.findall(rf'\b{re.escape(base)}\b', block)) != 3
                        or not re.search(rf'\b{re.escape(base)}\s*=\s*{re.escape(array)}\s*;', block)
                        or not _unconditional_extern(clean, array, r'(?:(?:unsigned|signed)\s+)?char')
                        or len(re.findall(rf'\b{re.escape(array)}\b', clean[:part.opening])) != 1):
                    break
                replacement = f'{row} = (s32 *)(({index} * 4) + (u32){base});'
                out.append((SLOT_FAMILY, edit(source, [(hit.start(), hit.end(), replacement)])))
                # The address change and an extra scope can be profitable only
                # together: each alone regressed in a linked KMC O1 case.
                scope = re.compile(rf'do\s*\{{\s*{re.escape(base)}\s*=\s*{re.escape(array)}\s*;\s*\}}\s*while\s*\(\s*0\s*\)\s*;')
                scopes = list(scope.finditer(block))
                if len(scopes) == 1 and len(out) < LIMIT:
                    start = a + 1 + scopes[0].start()
                    end = a + 1 + scopes[0].end()
                    weighted = f'do {{ do {{ {base} = {array}; }} while (0); }} while (0);'
                    out.append((PAIRED_FAMILY, edit(source, [(start, end, weighted),
                                                            (hit.start(), hit.end(), replacement)])))
                if len(out) >= LIMIT:
                    return out
                break
    return out


REPAIR = {'families': (FAMILY, SLOT_FAMILY, PAIRED_FAMILY), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
