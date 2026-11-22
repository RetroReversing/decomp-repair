"""Four widths and shapes a sound-engine key/velocity function needed, each a source edit the permuter lacked.

Matched on a 231-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) that stood at 500: a four-way
dispatch on a packed word that clamps a level, remaps a key and a velocity through a table, and calls three callees.
Each step below was found by hand with the judge (500 -> 555 -> 380 -> 260 -> 0; the evidence is in decompdecomp's
COMPILER_MATCHING_LEARNINGS.md), and each is offered here as a rewrite of its own plus the whole chain as one child,
since none of them but the last moves the score alone in the direction the next needs:

* `halfword_shift_cast`: `((unsigned short) x) >> 16` is the constant 0 (the cast drops the half the shift keeps), so
  every use of the id it fed compiled as zero. The id is `x >> 16`.
* `halfword_local_width`: `u32 id = x >> 16;` where `x` is a 32-bit word becomes `u16 id`. The target keeps the id in
  a register whose prologue copy the second scheduler places before the key's copy (`sw $s6; srl $s6,$s3,16` ahead
  of `sw $s5; move $s5,$a1`); with a word-typed local the two copies were in the other order (380 -> 260; hypothesis:
  a halfword pseudo is a different register class of copy, not confirmed in the compiler source).
* `mask_parameter_narrow`: a word parameter that is only ever read as `p & 0xFF` (or `p & 0x7F`, `p & 0x80`: any
  byte-or-smaller mask), alone or passed whole to a `static` helper that masks it the same way, becomes `u8 p` with
  the full-byte masks dropped (and the helper's parameter narrowed with it, as a second child). The narrow parameter's
  copy is placed after the body's first statements, the word's at the entry, and the byte was also what the target's
  `andi $a0,$s5,0x7f` read (555 -> 745 with the parameter alone, 380 with the helper's as well).
* `clamp_range_flag`: `if (x < 0) v = 0; else if (x < K) v = x; else v = C;` with the range test computed into a flag
  before the sign test: `f = x < K; if (x < 0) v = 0; else if (!f) v = C; else v = x;`. With the test inside the
  chain, jump.c hoists a copy of `v = x` above the compare and the second scheduler puts it first, so the compare read
  the copy's register (`move s4,v1; slti v0,s4,0x80; beql`); the target computed `slti v0,v1,0x80` before the sign
  test's `bgez`, which then took it in its delay slot, and `bnez v0; move s4,v1` closed the clamp (260 -> 0; the
  explanation is a hypothesis from cc1 -dj/-dS/-dR dumps, not confirmed in the compiler source).

`narrow_clamp_chain` applies every one of those that fits as one child (two or more). A candidate rewrite each; the
exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILIES = ('halfword_shift_cast', 'halfword_local_width', 'mask_parameter_narrow', 'clamp_range_flag',
            'narrow_clamp_chain')
WORD = r'(?:u32|unsigned\s+int|unsigned|s32|int)'
HALF = r'(?:u16|unsigned\s+short)'
BYTE_MASK = re.compile(r'0[xX]([0-9a-fA-F]{1,2})\b')


def _parameters(part):
    header = re.search(r'\(([^()]*)\)\s*$', part.clean[:part.opening])
    if not header:
        return {}, 0
    found, base = {}, header.start(1)
    for piece in re.finditer(rf'(?P<type>(?:const\s+)?[A-Za-z_][\w\s]*?\*?)\s*(?P<name>{IDENT})\s*(?:,|$)', header[1]):
        found[piece['name']] = (base + piece.start('type'), base + piece.end('type'), piece['type'].strip())
    return found, base


def _shift_cast(source, part):
    """(start, end, replacement) for each `((u16) x) >> 16` in the function."""
    edits = []
    body = part.clean
    pattern = rf'\(\s*\(\s*{HALF}\s*\)\s*({IDENT})\s*\)\s*>>\s*16\b|\(\s*{HALF}\s*\)\s*({IDENT})\s*>>\s*16\b'
    for hit in re.finditer(pattern, body[part.opening:part.end]):
        name = hit[1] or hit[2]
        edits.append((part.opening + hit.start(), part.opening + hit.end(), f'{name} >> 16'))
    return edits


def _local_width(source, part, params):
    """Retype `WORD id = x >> 16;` (x a 32-bit parameter or local) as a halfword."""
    edits = []
    body = part.clean[part.opening:part.end]
    for hit in re.finditer(rf'\b(?P<type>{WORD})\s+(?P<name>{IDENT})\s*=\s*(?P<src>{IDENT})\s*>>\s*16\s*;', body):
        name, origin = hit['name'], hit['src']
        wide = origin in params and re.fullmatch(r'u32|unsigned(?:\s+int)?', params[origin][2]) \
            or re.search(rf'\b(?:u32|unsigned(?:\s+int)?)\s+{origin}\b', body)
        others = re.findall(rf'(?<![\w.>]){name}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', body)
        if not wide or len(others) != 1 or re.search(rf'&\s*{name}\b', body):
            continue
        start = part.opening + hit.start('type')
        edits.append((start, start + len(hit['type']), 'u16'))
    return edits


def _helper_parameter(clean, helper, index):
    """The (start, end, text) of the `index`th parameter of a `static` helper defined in the source, and its body."""
    definition = re.search(rf'\bstatic\b[^;{{}}]*?\b{re.escape(helper)}\s*\(([^()]*)\)\s*{{', clean)
    if not definition:
        return None
    pieces = list(re.finditer(rf'(?P<type>[A-Za-z_][\w\s]*?)\s*(?P<name>{IDENT})\s*(?:,|$)', definition[1]))
    if index >= len(pieces):
        return None
    depth, end = 0, definition.end() - 1
    for i in range(end, len(clean)):
        depth += (clean[i] == '{') - (clean[i] == '}')
        if depth == 0:
            end = i
            break
    piece = pieces[index]
    base = definition.start(1)
    return (base + piece.start('type'), base + piece.end('type'), piece['type'].strip(), piece['name'],
            clean[definition.end():end])


def _only_byte_masked(text, name):
    uses = list(re.finditer(rf'(?<![\w.>]){name}\b', text))
    if not uses:
        return False
    for use in uses:
        tail = text[use.end():use.end() + 24]
        mask = re.match(r'\s*&\s*(0[xX][0-9a-fA-F]+|\d+)\b', tail)
        if not mask or int(mask[1], 0) > 0xFF:
            return False
        if re.match(r'\s*[-+*/|&^]?=(?!=)', tail) or re.search(r'&\s*$', text[:use.start()]):
            return False
    return True


def _byte_parameter(source, part, params):
    """[(function edits, helper edits)] for each word parameter read only through byte masks."""
    body = part.clean[part.opening:part.end]
    found = []
    for name, (start, end, text) in params.items():
        if not re.fullmatch(WORD, text):
            continue
        changed = re.search(rf'(?<![\w*.>]){name}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?<!&)&\s*{name}\b'
                            rf'|(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--)', body)
        uses = list(re.finditer(rf'(?<![\w.>]){name}\b', body))
        if changed or not uses:
            continue
        function_edits, helper_edits, ok = [(start, end, 'u8')], [], True
        for use in uses:
            tail = body[use.end():use.end() + 24]
            mask = re.match(r'\s*&\s*(0[xX][0-9a-fA-F]+|\d+)\b', tail)
            if mask and int(mask[1], 0) <= 0xFF:
                if int(mask[1], 0) == 0xFF:  # the full-byte mask is what the narrow type does by itself
                    function_edits.append((part.opening + use.end(), part.opening + use.end() + mask.end(), ''))
                continue
            call = re.search(rf'({IDENT})\s*\(([^()]*)$', body[:use.start()])
            if call and re.match(r'\s*[,)]', tail):
                position = call[2].count(',')
                helper = _helper_parameter(part.clean, call[1], position)
                if helper and re.fullmatch(WORD, helper[2]) and _only_byte_masked(helper[4], helper[3]):
                    helper_edits.append((helper[0], helper[1], 'u8'))
                    continue
            ok = False
            break
        if ok:
            found.append((function_edits, sorted(set(helper_edits))))
    return found


_CLAMP = re.compile(
    rf'(?P<indent>[ \t]*)if\s*\(\s*(?P<x>{IDENT})\s*<\s*0\s*\)\s*{{?\s*(?P<v>{IDENT})\s*=\s*0\s*;\s*}}?\s*'
    rf'else\s*if\s*\(\s*(?P=x)\s*<\s*(?P<k>0[xX][0-9a-fA-F]+|\d+)\s*\)\s*{{?\s*(?P=v)\s*=\s*(?P=x)\s*;\s*}}?\s*'
    rf'else\s*{{?\s*(?P=v)\s*=\s*(?P<c>0[xX][0-9a-fA-F]+|\d+)\s*;\s*}}?')


def _clamp_flag(source, part):
    """(start, end, text) for each clamp chain, the flag declared at the head of the function."""
    edits = []
    body = part.clean[part.opening:part.end]
    taken = set(re.findall(IDENT, body))
    for number, hit in enumerate(_CLAMP.finditer(body)):
        flag = f'{hit["x"]}InRange'
        while flag in taken:
            flag += '_'
        taken.add(flag)
        indent = hit['indent']
        text = (f'{indent}{flag} = {hit["x"]} < {hit["k"]};\n'
                f'{indent}if ({hit["x"]} < 0) {hit["v"]} = 0; else if (!{flag}) {hit["v"]} = {hit["c"]}; '
                f'else {hit["v"]} = {hit["x"]};')
        edits.append((part.opening + hit.start(), part.opening + hit.end(), text, flag))
    return edits


def _declare(source, part, flags):
    """Declare each flag as an `s32` right after the function's opening brace line."""
    line = source.find('\n', part.opening) + 1
    return (line, line, ''.join(f'  s32 {flag};\n' for flag in flags))


def _each(source, name):
    """[(family, [edits])] for every single rewrite the function takes as it stands."""
    part = view(source, name)
    if not part:
        return []
    params, _ = _parameters(part)
    found = []
    casts = _shift_cast(source, part)
    found += [('halfword_shift_cast', [one]) for one in casts]
    if len(casts) > 1:
        found.append(('halfword_shift_cast', casts))
    found += [('halfword_local_width', [one]) for one in _local_width(source, part, params)]
    for function_edits, helper_edits in _byte_parameter(source, part, params):
        found.append(('mask_parameter_narrow', function_edits))
        if helper_edits:
            found.append(('mask_parameter_narrow', function_edits + helper_edits))
    for clamp in _clamp_flag(source, part):
        found.append(('clamp_range_flag', [clamp[:3], _declare(source, part, [clamp[3]])]))
    return found


def variants(source, name):
    out = [(family, edit(source, edits)) for family, edits in _each(source, name)]
    # the whole chain: each family's first rewrite, one after another, since a later one reads the text an earlier one
    # leaves (the halfword local only exists once the cast is gone)
    chained, text, applied = [], source, set()
    for _ in range(6):
        options = [(family, edits) for family, edits in _each(text, name) if family not in applied]
        # the widest rewrite of the first family that still applies (the helper's parameter too, every cast)
        step = next(((family, edits) for family, edits in reversed(options) if family == options[0][0]), None) \
            if options else None
        if not step:
            break
        applied.add(step[0])
        chained.append(step[0])
        text = edit(text, step[1])
    if len(chained) > 1:
        out.append(('narrow_clamp_chain', text))
    return out
