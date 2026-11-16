"""Declared indexed records and raw MIPS base evidence for bounded copy hypotheses.

Unknown layouts, aliases, shadowed roots and effectful indices decline. Qualifiers
belong to each access: a volatile word does not make two ordinary byte fields
volatile. This reader supplies candidate evidence, never a match verdict.
"""
import math
import re
from dataclasses import dataclass

from .csource import _blank, find
from .integer_abi import scalar
from .integer_repair_support import IDENT, integer, view

SCALARS = {'char': (1, 1), 's8': (1, 1), 'u8': (1, 1), 'short': (2, 2),
           's16': (2, 2), 'u16': (2, 2), 'int': (4, 4), 's32': (4, 4),
           'u32': (4, 4), 'float': (4, 4), 'f32': (4, 4)}
INDEX = rf'(?:{IDENT}|[0-9]+|0[xX][0-9a-fA-F]+)(?:\s*\+\s*(?:{IDENT}|[0-9]+))?'
ACCESS = rf'{IDENT}(?:(?:->|\.){IDENT}|\[\s*{INDEX}\s*\])*'
FIELD = rf'{ACCESS}(?:->|\.){IDENT}'


@dataclass(frozen=True)
class Value:
    type: str
    size: int
    align: int
    dims: tuple = ()
    pointer: bool = False
    volatile: bool = False
    offset: int = 0
    declaration: tuple = ()


class Records:
    def __init__(self, source, name, header=''):
        self.part = view(source, name)
        self.types, self.roots = {}, {}
        context = _blank(header)+'\n'+_blank(source)
        self.macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')\b', context, re.M))
        if (not self.part or re.search(r'\b(?:asm|__asm__|union|restrict|__restrict)\b', self.part.body)
                or re.search(r'\b__LINE__\b|^\s*#\s*(?:line\b|[0-9])', context, re.M)):
            self.part = None
            return
        for typ in re.findall(r'\b[su](?:8|16|32)\b', _blank(source)):
            if scalar(typ, context, 'mips') != (int(typ[1:]), typ[0] == 's'):
                self.part = None
                return
        if re.search(r'\bf32\b', _blank(source)):
            floats = re.findall(r'\btypedef\s+([^;{}]+?)\bf32\s*;', context)
            if not floats or any(t.strip() != 'float' for t in floats):
                self.part = None
                return
        clean = _blank(source)
        spans = []
        pattern = rf'\btypedef\s+struct(?:\s+{IDENT})?\s*{{([^{{}}]*)}}\s*({IDENT})\s*;'
        seen_types = set()
        for match in re.finditer(pattern, clean):
            spans.append(match.span())
            if match[2] in seen_types:
                self.types.pop(match[2], None)
                continue
            seen_types.add(match[2])
            members, offset, alignment = {}, 0, 1
            for declaration in re.finditer(r'([^;]+);', match[1]):
                text = declaration[1].strip()
                field = re.fullmatch(rf'(volatile\s+)?({IDENT})\s+(\*?)(\s*{IDENT})((?:\s*\[\s*(?:0x[0-9a-fA-F]+|[0-9]+)\s*\])*)', text)
                if not field or field[4].strip() in members:
                    break
                qualified, typ, pointer, member, suffix = field.groups()
                size_align = (4, 4) if pointer else self.size(typ)
                if size_align is None:
                    break
                size, align = size_align
                dims = tuple(integer(n) for n in re.findall(r'\[\s*(0x[0-9a-fA-F]+|[0-9]+)\s*\]', suffix))
                if any(n < 1 or n > 65536 for n in dims):
                    break
                offset = (offset+align-1)//align*align
                start = match.start(1)+declaration.start(1)
                # Only candidate-owned declaration spans may be qualified.
                members[member.strip()] = Value(typ, size*math.prod(dims), align, dims, bool(pointer),
                                                bool(qualified), offset, (start, start+len(declaration[1])))
                offset += size*math.prod(dims)
                alignment = max(alignment, align)
            else:
                if members and match[2] not in self.types:
                    self.types[match[2]] = (members, (offset+alignment-1)//alignment*alignment, alignment)
        # Ignore members when finding roots; declarations from sibling scopes are
        # ambiguous rather than guessed. Scalar comma declarations are common.
        masked = clean
        for a, b in reversed(spans):
            masked = masked[:a]+' '*(b-a)+masked[b:]
        kinds = '|'.join(sorted(set(SCALARS)|self.types.keys(), key=len, reverse=True))
        decl = rf'\b(?:extern\s+)?(volatile\s+)?({kinds})\s+(\*?)\s*({IDENT})((?:\s*\[\s*(?:0x[0-9a-fA-F]+|[0-9]*)\s*\])*)\s*(?=[;=,)])'
        seen = set()
        for hit in re.finditer(decl, masked):
            qualified, typ, pointer, root, suffix = hit.groups()
            if root in seen:
                self.roots.pop(root, None)
                continue
            seen.add(root)
            dims = tuple(integer(n) if n else 0 for n in re.findall(r'\[\s*(0x[0-9a-fA-F]+|[0-9]*)\s*\]', suffix))
            size, align = (4, 4) if pointer else self.size(typ)
            self.roots[root] = Value(typ, size, align, dims, bool(pointer), bool(qualified), declaration=hit.span())
        for hit in re.finditer(rf'\b(u8|s8|u16|s16|u32|s32)\s+({IDENT}(?:\s*,\s*{IDENT})+)\s*;', masked):
            for root in re.findall(IDENT, hit[2]):
                if root not in seen:
                    size, align = self.size(hit[1])
                    self.roots[root] = Value(hit[1], size, align)

    def size(self, typ):
        if typ in SCALARS:
            return SCALARS[typ]
        record = self.types.get(typ)
        return record[1:] if record else None

    def access(self, expression):
        if self.macros.intersection(re.findall(IDENT, expression)):
            return None
        # The commuted form is only emitted for a pure index and member array.
        expression = re.sub(rf'\b({IDENT})\[({IDENT}->{IDENT})\]', r'\2[\1]', expression)
        expression = re.sub(r'\s+', '', expression)
        first = re.match(IDENT, expression)
        value = self.roots.get(first[0]) if first else None
        if value is None:
            return None
        pos = first.end()
        while pos < len(expression):
            tail = expression[pos:]
            subscript = re.match(rf'\[({INDEX})\]', tail)
            if subscript:
                if not value.dims and not value.pointer:
                    return None
                dims = value.dims[1:] if value.dims else ()
                size, align = self.size(value.type)
                value = Value(value.type, size*math.prod(dims), align, dims, False, value.volatile,
                              value.offset, value.declaration)
                pos += subscript.end()
                continue
            field = re.match(rf'(->|\.)({IDENT})', tail)
            if not field or value.dims or bool(value.pointer) != (field[1] == '->'):
                return None
            record = self.types.get(value.type)
            if not record or field[2] not in record[0]:
                return None
            member = record[0][field[2]]
            value = Value(member.type, member.size, member.align, member.dims, member.pointer,
                          value.volatile or member.volatile, member.offset, member.declaration)
            pos += field.end()
        return value


def indexed_bases(asm, *, memory=False):
    """Raw base+dynamic-index anchors; not absolute effective addresses of indexed accesses."""
    registers, found, accesses, previous, epoch = {}, set(), [], None, 0
    for pc, text in re.findall(r'/\*\s*[0-9a-fA-F]+\s+([0-9a-fA-F]{8})\s+([0-9a-fA-F]{8})\s*\*/', asm or ''):
        pc, word = int(pc, 16), int(text, 16)
        if previous is not None and pc != previous+4:
            registers.clear()
            epoch += 1
        previous = pc
        op, rs, rt, rd = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31
        low = word & 65535
        low = low if low < 32768 else low-65536
        if op == 15:
            registers[rt] = (word & 65535) << 16
        elif op == 0 and word & 63 in {33, 45} and rs != rt:
            a, b = registers.get(rs), registers.get(rt)
            registers.pop(rd, None)
            if (a is None) != (b is None):
                registers[rd] = a if a is not None else b
        elif op in {9, 13, 32, 33, 35, 36, 37, 40, 41, 43, 49, 53, 57, 61}:
            base = registers.get(rs)
            address = ((base | (word & 65535)) if op == 13 else base+low) & 0xffffffff if base is not None else None
            if address is not None:
                found.add(address)
                if op not in {9, 13}:
                    accesses.append((epoch, pc, op, address))
            if op in {9, 13}:
                registers.pop(rt, None)
                if address is not None:
                    registers[rt] = address
            elif op in {32, 33, 35, 36, 37}:
                registers.pop(rt, None)
        elif op == 0 and word & 63 not in {8, 9, 12, 13}:
            if word:
                registers.pop(rd, None)
        else:
            registers.clear()
            epoch += 1
    return accesses if memory else found


def part(source, name, header=''):
    model = Records(source, name, header)
    if not model.part or len(source)+len(header) > 128000 or not find(source, name):
        return None
    return model
