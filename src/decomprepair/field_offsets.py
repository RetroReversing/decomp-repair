"""A donor's struct fields moved to where the target game has them.

Two games built from one source often differ only in a struct's layout: a field added before the ones a function reads
moves them all by four bytes, and the function's code is the same apart from its load and store offsets. Another game's
matched C (decompdecomp's similar-code pass) then compiles to the target's instructions with the wrong offsets, and no
number in the C says them: they come from the struct's definition. A literal edit can't reach them.

`pairs` reads which offsets differ from the candidate's compiled body and the target, instruction by instruction (same
opcode and registers, a load or store off a pointer other than the stack or the small-data base, no relocation). 
`from_pairs` finds the struct field each old offset belongs to, among the fields the function reads through a typed
pointer: `p->field`, `p->pos.x` (offsets add up inside a struct value), `a[i].field`, `p[i].field` and each
dereference of a chain such as `p->next->hp`. It offers two C texts:
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


class Access:
    """One load or store a C expression makes off a struct: `p->a.b` (one access, at a's offset plus b's, off `p`),
    and in `p->next->hp` two (`next` off `p`, `hp` off `p->next`)."""

    def __init__(self, start, end, chain, group, struct, member, offset):
        self.start, self.end, self.chain, self.group = start, end, chain, group
        self.struct, self.member, self.offset = struct, member, offset

    def key(self):
        return (id(self.struct), self.offset)


DECLARED = re.compile(r'((?:struct\s+)?[A-Za-z_]\w*)\s+((?:\*\s*)?)([A-Za-z_]\w*)\s*((?:\[[^\]]*\])?)\s*(?=[,;)=\[])')
CHAIN = re.compile(r'(?<![\w.>&])([A-Za-z_]\w*)(\s*\[[^\[\]]*\])?((?:\s*(?:->|\.)\s*[A-Za-z_]\w*)+)')
STEP = re.compile(r'\s*(->|\.)\s*([A-Za-z_]\w*)')


def _declarations(source, types):
    """{variable: (struct, pointer, array)} for what the source declares as a struct, a pointer to one or an array."""
    out = {}
    for m in DECLARED.finditer(_blank(source)):
        found = types.struct(m.group(1))
        if found is not None and m.group(2).count('*') <= 1:
            out.setdefault(m.group(3), (found, bool(m.group(2).strip()), bool(m.group(4))))
    return out


def _chains(source, types):
    """[(start, end, base text, [(operator, text, Access)])]: each struct expression and the accesses it makes."""
    clean = _blank(source)
    declared = _declarations(source, types)
    out = []
    for m in CHAIN.finditer(clean):
        decl = declared.get(m.group(1))
        if decl is None:
            continue
        current, pointer, array = decl
        steps = list(STEP.finditer(m.group(3)))
        first = steps[0].group(1)
        indexed = bool(m.group(2))
        if (first == '->') != (pointer and not indexed) or (first == '.' and pointer and not indexed):
            continue
        if first == '.' and not indexed and array:
            continue
        groups, offset, member, struct, ok = [], 0, None, current, True
        base = m.start(3)
        for index, step in enumerate(steps):
            if index and step.group(1) == '->':
                if member is None or member.stars != 1 or member.dims:
                    ok = False
                    break
                groups.append((struct, member, offset, base, m.start(3) + step.start()))
                struct = types.struct(member.ctype)
                if struct is None:
                    ok = False
                    break
                offset, base = 0, m.start(3) + step.start()
            elif index:
                if member is None or member.stars or member.dims:
                    ok = False
                    break
                inner = types.struct(member.ctype)
                if inner is None:
                    ok = False
                    break
                container = inner  # offsets stay relative to the dereferenced struct
                member = next((x for x in container.members if x.name == step.group(2)), None)
                if member is None:
                    ok = False
                    break
                offset += member.offset
                continue
            container = struct
            member = next((x for x in container.members if x.name == step.group(2)), None)
            if member is None:
                ok = False
                break
            offset = member.offset if step.group(1) == '->' or index == 0 else offset + member.offset
        if not ok or member is None:
            continue
        groups.append((struct, member, offset, base, m.end(3)))
        accesses = [Access(m.start(), m.end(), m, (start, stop), group_struct, last, at)
                    for group_struct, last, at, start, stop in groups]
        out.append((m, accesses))
    return out


def _accesses(source, types):
    return [access for _, accesses in _chains(source, types) for access in accesses]


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


def _spelled(member):
    return (member.ctype + ' ' + '*' * member.stars).strip()


def from_pairs(source, header, offsets):
    """C texts with the fields at `offsets` ({old: new}) moved: the struct laid out again, and the uses rewritten."""
    if not offsets or not source:
        return []
    types = Types(source, header)
    chains = _chains(source, types)
    by_offset = {}
    for _, accesses in chains:
        for access in accesses:
            if access.offset in offsets:
                by_offset.setdefault(access.offset, {})[access.key()] = access
    moved = {}  # access key -> new offset, only where one struct field has the old offset
    for old, keys in by_offset.items():
        if len(keys) == 1:
            moved[next(iter(keys))] = offsets[old]
    if not moved:
        return []
    out = []
    # The struct laid out again: only for a moved field read directly (not inside a nested struct value).
    direct = {}
    for _, accesses in chains:
        for access in accesses:
            if access.key() in moved:
                if access.member.offset != access.offset or not access.struct.in_source:
                    direct = None
                    break
                direct[id(access.member)] = (moved[access.key()], access.struct)
        if direct is None:
            break
    if direct:
        edits, ok = {}, True
        for structure in {id(s): s for _, s in direct.values()}.values():
            text = _relayout(structure, {key: at for key, (at, s) in direct.items() if s is structure})
            if text is None:
                ok = False
                break
            edits[(structure.start, structure.end)] = text
        if ok:
            relaid = source
            for (start, end), text in sorted(edits.items(), reverse=True):
                relaid = relaid[:start] + text + relaid[end:]
            out.append(relaid)
    # Every use written at its new offset, whatever header defines the struct.
    rewritten = source
    for m, accesses in sorted(chains, key=lambda item: -item[0].start()):
        if not any(access.key() in moved for access in accesses):
            continue
        expr = source[m.start():m.start(3)]
        for index, access in enumerate(accesses):
            start, stop = access.group
            if access.key() in moved and not access.member.dims and not (
                    access.member.stars == 0 and types.struct(access.member.ctype) is not None):
                via_value = index == 0 and source[start:stop].lstrip().startswith('.')
                base = '&' + expr if via_value else expr
                plain = re.fullmatch(r'[A-Za-z_]\w*', base)
                expr = f'(*({_spelled(access.member)} *)((char *){base if plain else "(" + base + ")"} + 0x{moved[access.key()]:X}))'
            else:
                expr += source[start:stop]
        rewritten = rewritten[:m.start()] + expr + rewritten[m.end():]
    if rewritten != source:
        out.append(rewritten)
    return [text for text in dict.fromkeys(out) if text != source]


def variants(source, name, header='', asm=''):
    """The target's distinct struct offsets paired in order with the ones the function reads through its one struct
    type, when both have the same number and differ (a field inserted before them)."""
    types = Types(source, header)
    accesses = _accesses(source, types)
    kinds = {id(access.struct) for access in accesses}
    if len(kinds) != 1:
        return []
    mine = sorted({access.offset for access in accesses})
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
