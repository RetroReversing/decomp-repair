"""A donor's struct fields moved to where the target game has them.

Two games built from one source often differ only in a struct's layout: a field added before the ones a function reads
moves them all by four bytes, and the function's code is the same apart from its load and store offsets. Another game's
matched C (decompdecomp's similar-code pass) then compiles to the target's instructions with the wrong offsets, and no
number in the C says them: they come from the struct's definition. A literal edit can't reach them.

`pairs` reads which offsets differ from the candidate's compiled body and the target, instruction by instruction (same
opcode and registers, a load or store off a pointer other than the stack or the small-data base, no relocation). 
`from_pairs` finds the struct field each old offset belongs to, among the fields the function reads through a typed
pointer (`p->field`), and offers two C texts:
- the struct's definition with padding before each moved field, so it lands at its new offset and the fields after it
  follow, when the definition is in the source (a donor's type brought with its C);
- every use of a moved field written at its new offset (`(*(s16 *)((char *)p + 0x16))`), which works whatever header
  defines the struct.
An offset that two of the read fields share, a field that would overlap another or lose its alignment, a bitfield, a
union or a type this reader can't size: nothing is offered for it. Only the judge decides whether either text matches.

`variants` (the registry's lanes, which have the target's assembly but no compiled candidate) pairs the distinct offsets
the function reads through its one struct pointer with the target's distinct load/store offsets, in order, when both
sets are the same size and differ: the inserted-field case. MIPS O32 sizes and alignment (IDO, GCC, SN)."""
import re

FAMILY = 'field_offsets'
FAMILIES = (FAMILY,)

SCALARS = {
    'char': 1, 'signed char': 1, 'unsigned char': 1, 'u8': 1, 's8': 1, 'uint8_t': 1, 'int8_t': 1, 'bool': 1,
    'short': 2, 'signed short': 2, 'unsigned short': 2, 'short int': 2, 'unsigned short int': 2,
    'u16': 2, 's16': 2, 'uint16_t': 2, 'int16_t': 2,
    'int': 4, 'signed int': 4, 'unsigned int': 4, 'unsigned': 4, 'signed': 4, 'long': 4, 'unsigned long': 4,
    'long int': 4, 'unsigned long int': 4, 'u32': 4, 's32': 4, 'uint32_t': 4, 'int32_t': 4, 'f32': 4, 'float': 4,
    'size_t': 4, 'uintptr_t': 4, 'intptr_t': 4,
    'long long': 8, 'unsigned long long': 8, 'u64': 8, 's64': 8, 'uint64_t': 8, 'int64_t': 8, 'f64': 8, 'double': 8,
}
# lb lh lwl lw lbu lhu lwr lwu sb sh swl sw sdl sdr swr ld sd lwc1 ldc1 swc1 sdc1
LOAD_STORE = {32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 55, 63, 49, 53, 57, 61}
STACK_REGISTERS = {28, 29, 30}  # $gp, $sp and $fp: offsets off them are the frame's and small data's, not a struct's
STRUCT = re.compile(r'(?P<typedef>\btypedef\s+)?\bstruct\s+(?P<tag>[A-Za-z_]\w*)?\s*\{')
ALIAS = re.compile(r'\btypedef\s+(?P<type>(?:struct\s+)?[A-Za-z_][\w ]*?)\s+(?P<name>[A-Za-z_]\w*)\s*;')
COMMENT = re.compile(r'/\*.*?\*/|//[^\n]*', re.S)
ASM_ACCESS = re.compile(r'^(?:l[bhwd]u?|s[bhwd]|l[wd]c1|s[wd]c1)\s+\$\w+,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\(\$(\w+)\)\s*$')


class Member:
    def __init__(self, name, ctype, stars, dims, offset, size, align):
        self.name, self.ctype, self.stars, self.dims = name, ctype, stars, dims
        self.offset, self.size, self.align = offset, size, align

    def declaration(self):
        return f"{self.ctype} {'*' * self.stars}{self.name}{''.join(f'[{d}]' for d in self.dims)};"


class Struct:
    def __init__(self, tag, alias, members, size, align, start, end, in_source):
        self.tag, self.alias, self.members = tag, alias, members
        self.size, self.align, self.start, self.end, self.in_source = size, align, start, end, in_source


def _blank(text):
    return COMMENT.sub(lambda m: ' ' * len(m.group(0)), text)


def _close(text, at):
    """The index just past the brace that closes the one at `at`, or -1."""
    depth = 0
    for m in re.finditer(r'[{}]', text[at:]):
        depth += 1 if m.group(0) == '{' else -1
        if depth == 0:
            return at + m.end()
    return -1


def _normal(ctype):
    return ' '.join(w for w in ctype.replace('\t', ' ').split() if w not in ('const', 'volatile', 'register'))


class Types:
    """The structs and simple typedefs of a source and its header, sized as MIPS O32 lays them out."""

    def __init__(self, source, header=''):
        self.raw, self.aliases, self.structs = {}, {}, {}
        for text, in_source in ((header or '', False), (source or '', True)):
            clean = _blank(text)
            for m in ALIAS.finditer(clean):
                if not m.group('type').strip().startswith('struct') or m.group('type').split()[-1] != m.group('name'):
                    self.aliases[m.group('name')] = _normal(m.group('type'))
            for m in STRUCT.finditer(clean):
                end = _close(clean, m.end() - 1)
                if end < 0:
                    continue
                tail = re.match(r'\s*([A-Za-z_]\w*)?\s*;', clean[end:])
                alias = tail.group(1) if tail and m.group('typedef') else None
                stop = end + tail.end() if tail else end
                key = m.group('tag') or alias
                if key:
                    self.raw[key] = (clean[m.end():end - 1], m.group('tag'), alias, m.start(), stop, in_source)
                    if alias and m.group('tag'):
                        self.aliases[alias] = 'struct ' + m.group('tag')

    def resolve(self, ctype, depth=0):
        ctype = _normal(ctype)
        while ctype in self.aliases and depth < 8:
            ctype, depth = self.aliases[ctype], depth + 1
        return ctype

    def struct(self, name, depth=0):
        """The struct a tag, a typedef or `struct Tag` names, laid out; None when any member can't be sized."""
        if depth > 6:
            return None
        name = self.resolve(name)
        key = name[7:].strip() if name.startswith('struct ') else name
        if key in self.structs:
            return self.structs[key]
        if key not in self.raw:
            return None
        body, tag, alias, start, end, in_source = self.raw[key]
        self.structs[key] = None  # a struct that holds itself (not through a pointer) can't be sized
        members, offset, align = [], 0, 1
        for part in body.split(';'):
            part = part.strip()
            if not part:
                continue
            if '{' in part or ':' in part or 'union' in part.split():
                return None
            fp = re.fullmatch(r'(.+?)\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\(.*\)', part, re.S)
            if fp:
                return None  # a function pointer's declaration doesn't survive a re-layout's simple rewrite
            m = re.fullmatch(r'((?:struct\s+)?[A-Za-z_][\w ]*?)\s*((?:\*\s*)*[A-Za-z_]\w*(?:\s*\[[^\]]*\])*'
                             r'(?:\s*,\s*(?:\*\s*)*[A-Za-z_]\w*(?:\s*\[[^\]]*\])*)*)', part, re.S)
            if not m:
                return None
            base = _normal(m.group(1))
            for declarator in m.group(2).split(','):
                d = re.fullmatch(r'\s*((?:\*\s*)*)([A-Za-z_]\w*)((?:\s*\[[^\]]*\])*)\s*', declarator)
                if not d:
                    return None
                stars = d.group(1).count('*')
                dims = re.findall(r'\[([^\]]*)\]', d.group(3))
                count = 1
                for dim in dims:
                    try:
                        count *= int(dim.strip(), 0)
                    except ValueError:
                        return None
                if stars:
                    size = alignment = 4
                else:
                    resolved = self.resolve(base)
                    if resolved in SCALARS:
                        size = alignment = SCALARS[resolved]
                    else:
                        inner = self.struct(resolved, depth + 1)
                        if inner is None:
                            return None
                        size, alignment = inner.size, inner.align
                offset = (offset + alignment - 1) // alignment * alignment
                members.append(Member(d.group(2), base, stars, dims, offset, size * count, alignment))
                offset += size * count
                align = max(align, alignment)
        size = (offset + align - 1) // align * align
        found = Struct(tag, alias, members, size, align, start, end, in_source)
        self.structs[key] = found
        return found


def pairs(compiled, target, relocated, big):
    """{old offset: new offset} for the struct accesses the compiled candidate and the target disagree on, read from
    aligned instructions that are the same apart from their offset. {} when an old offset goes two ways."""
    if not compiled or len(compiled) != len(target) or len(compiled) % 4:
        return {}
    order = 'big' if big else 'little'
    out = {}
    for at in range(0, len(compiled), 4):
        if at in relocated:
            continue
        x, y = int.from_bytes(compiled[at:at + 4], order), int.from_bytes(target[at:at + 4], order)
        if x == y or x >> 16 != y >> 16 or x >> 26 not in LOAD_STORE or (x >> 21) & 31 in STACK_REGISTERS:
            continue
        old, new = x & 0xffff, y & 0xffff
        old, new = old - 0x10000 if old >= 0x8000 else old, new - 0x10000 if new >= 0x8000 else new
        if out.setdefault(old, new) != new:
            return {}
    return out


def _pointers(source, types):
    """{variable: struct} for the variables the source declares as a pointer to a struct this reader can lay out."""
    out = {}
    clean = _blank(source)
    for m in re.finditer(r'((?:struct\s+)?[A-Za-z_]\w*)\s*\*\s*([A-Za-z_]\w*)\s*(?=[,;)=\[])', clean):
        found = types.struct(m.group(1))
        if found is not None:
            out.setdefault(m.group(2), found)
    return out


def _accesses(source, pointers):
    """[(start, end, variable, member)] for each `p->field` the source reads or writes, `p` a struct pointer."""
    out = []
    clean = _blank(source)
    for m in re.finditer(r'(?<![\w.>&])([A-Za-z_]\w*)\s*->\s*([A-Za-z_]\w*)', clean):
        found = pointers.get(m.group(1))
        if found is None:
            continue
        member = next((x for x in found.members if x.name == m.group(2)), None)
        if member is not None:
            out.append((m.start(), m.end(), m.group(1), member, found))
    return out


def _relayout(found, moved):
    """The struct's definition with padding before each moved member, so it lands at its new offset and the members
    after it follow (as when the other game's struct has a field inserted there), or None when one can't get there."""
    lines, at, index = [], 0, 0
    for member in found.members:
        at = (at + member.align - 1) // member.align * member.align
        offset = moved.get(id(member), at)
        if offset < at or offset % member.align:
            return None
        if offset > at:
            lines.append(f'char _pad{index:X}[0x{offset - at:X}];')
            index += 1
        lines.append(member.declaration())
        at = offset + member.size
    body = '\n    '.join(lines)
    head = ('typedef ' if found.alias else '') + 'struct' + (' ' + found.tag if found.tag else '')
    return f"{head} {{\n    {body}\n}}{' ' + found.alias if found.alias else ''};"


def from_pairs(source, header, offsets):
    """C texts with the fields at `offsets` ({old: new}) moved: the struct laid out again, and the uses rewritten."""
    if not offsets or not source:
        return []
    types = Types(source, header)
    pointers = _pointers(source, types)
    uses = _accesses(source, pointers)
    by_offset = {}
    for start, end, variable, member, found in uses:
        if member.offset in offsets:
            by_offset.setdefault(member.offset, {})[id(member)] = (member, found)
    moved = {}  # id(member) -> new offset, only where one read field has the old offset
    for old, members in by_offset.items():
        if len(members) == 1:
            moved[next(iter(members))] = offsets[old]
    if not moved:
        return []
    out = []
    structs = {id(found): found for _, _, _, member, found in uses if id(member) in moved}
    edits = []
    for found in structs.values():
        if found.in_source:
            text = _relayout(found, moved)
            if text is None:
                edits = []
                break
            edits.append((found.start, found.end, text))
    if edits:
        relaid = source
        for start, end, text in sorted(edits, reverse=True):
            relaid = relaid[:start] + text + relaid[end:]
        out.append(relaid)
    rewritten = source
    for start, end, variable, member, found in sorted(uses, key=lambda item: -item[0]):
        if id(member) not in moved or member.dims:
            continue
        spelled = member.ctype + ' ' + '*' * member.stars
        rewritten = (rewritten[:start] + f'(*({spelled.strip()} *)((char *){variable} + 0x{moved[id(member)]:X}))'
                     + rewritten[end:])
    if rewritten != source:
        out.append(rewritten)
    return [text for text in dict.fromkeys(out) if text != source]


def variants(source, name, header='', asm=''):
    """The target's distinct struct offsets paired in order with the ones the function reads through its one struct
    pointer type, when both have the same number and differ (a field inserted before them)."""
    types = Types(source, header)
    pointers = _pointers(source, types)
    uses = _accesses(source, pointers)
    kinds = {id(found) for _, _, _, _, found in uses}
    if len(kinds) != 1:
        return []
    mine = sorted({member.offset for _, _, _, member, _ in uses})
    theirs = set()
    for line in (asm or '').splitlines():
        line = line.split('*/', 1)[-1].strip()
        m = ASM_ACCESS.match(line)
        if m and m.group(2) not in ('sp', 'gp', 'fp', '29', '28', '30'):
            theirs.add(int(m.group(1), 0))
    theirs = sorted(theirs)
    if len(mine) != len(theirs) or mine == theirs or not mine:
        return []
    return [(FAMILY, text) for text in from_pairs(source, header, dict(zip(mine, theirs)))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'archs': ('mips',)}
