"""Trailing zero arguments a call lacks, read from the words the target stores above its register arguments.

m2c and hand-written drafts stop short on a callee declared `()` that takes a long run of arguments: the target stores
each one past the fourth at `0x10($sp)`, `0x14($sp)`, ... before the `jal`, and a call two arguments short compiles a
frame 8 bytes smaller, so every saved register's slot and the epilogue differ too. On a KMC 2.7.2 `-O1` function the
18-argument call was written with 16 (233, 18 stack rows); the two zeros were most of the way to the match. An
earlier draft had hidden the frame with an unused `volatile` local, so a second child also drops such a local.

The prologue sits in the first call's block, so its saves (`sw $s0, 0x48($sp)`, `sw $ra, 0x4C($sp)`) are not
argument words: a saved register's slot is the one the function loads the same register back from. A draft's trailing
float zero (`(float) 0`, `0.0f`: m2c's guess at a word, passed as a double to a `()` callee) counts as the integer zero
the target stores. On a KMC 2.7.2 `-O1` menu setup the saves hid both calls and the float zero hid one more.

The target says which words are zero, and a word whose register was set by `addiu $r, $zero, N` (or `ori`) just
before the store is that constant: a KMC GCC 2.7.2 `-O1` function (670 points) called a four-parameter callee with
four arguments where the target also stores 0x46 at `0x10($sp)` in both arms of an `if`; appending `0x46` and widening
the callee's prototype by one parameter was exact. A word loaded from anywhere else is not guessed."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'stack_argument_tail'
FAMILIES = (FAMILY,)
MAXIMUM = 40  # words
_CALL = re.compile(rf'\bjal\s+({IDENT})')
_BRANCH = re.compile(r'\b(?:jalr?|jr|j|b[a-z0-9]*)\s')
_STORE = re.compile(r'\bsw\s+\$(\w+)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_LOAD = re.compile(r'\blw\s+\$(\w+)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_SAVED = re.compile(r'ra|fp|s[0-8]')
_IMMEDIATE = re.compile(r'\b(?:addiu|ori|li)\s+\$(\w+)\s*,\s*(?:\$zero\s*,\s*)?(-?(?:0x[0-9a-fA-F]+|\d+))\s*$')
_WRITES = re.compile(r'^\s*(?!sw\b|sb\b|sh\b|swc1\b|b|j|nop)\w+\s+\$(\w+)\s*,')
_FLOAT_ZERO = re.compile(r'\(\s*(?:float|double|f32|f64)\s*\)\s*0(?:\.0*)?[fF]?|0\.0*[fF]?')


def _calls(asm):
    """(callee, the lines of its block in program order with the delay slot last, the prologue's saved slots, all the
    function's lines, where the block starts in them)."""
    lines = [line for line in asm.splitlines() if line.strip() and not line.rstrip().endswith(':')]
    saves = {(hit[1], int(hit[2], 0)) for hit in map(_LOAD.search, lines) if hit and _SAVED.fullmatch(hit[1])}
    for index, line in enumerate(lines):
        call = _CALL.search(line)
        if not call:
            continue
        earlier = []
        for before in reversed(lines[:index]):
            if _BRANCH.search(before):
                break
            earlier.append(before)
        yield call[1], earlier[::-1] + lines[index + 1:index + 2], saves, lines, index - len(earlier)


def target_words(asm):
    """{callee: {argument index: stored register}} for the words each call's block puts at 0x10($sp) and above,
    counted only while they are contiguous."""
    found = {}
    for callee, block, saves, _, _ in _calls(asm):
        stores = {}
        for text in reversed(block):
            hit = _STORE.search(text)
            if hit and (hit[1], int(hit[2], 0)) not in saves:
                stores.setdefault(int(hit[2], 0), hit[1])
        words = {}
        offset = 0x10
        while offset in stores and len(words) < MAXIMUM:
            words[offset // 4] = stores[offset]
            offset += 4
        if len(words) > len(found.get(callee, {})):
            found[callee] = words
    return found


def target_constants(asm):
    """{callee: {argument index: constant}} for the stack words whose register an immediate load set before the store
    (`addiu $v0, $zero, 0x46; sw $v0, 0x10($sp)`), however far back in the function and across branches, up to the
    previous call; a register written any other way gives no constant. A load in a branch's delay slot counts, and
    one constant may serve both arms."""
    found = {}
    for callee, block, saves, lines, start in _calls(asm):
        values = {}
        for at, text in enumerate(block):
            hit = _STORE.search(text)
            if not hit or (hit[1], int(hit[2], 0)) in saves or hit[1] == 'zero':
                continue
            for before in reversed(lines[:start + at]):
                if re.search(r'\b(?:jalr?|jr)\s', before):
                    break
                imm = _IMMEDIATE.search(before)
                if imm and imm[1] == hit[1]:
                    values[int(hit[2], 0) // 4] = int(imm[2], 0)
                    break
                if (write := _WRITES.search(before)) and write[1] == hit[1]:
                    break
        if len(values) > len(found.get(callee, {})):
            found[callee] = values
    return found


def _arguments(clean, opening):
    """(position of the closing parenthesis, argument count) of the call whose `(` is at `opening`."""
    depth, commas = 0, 0
    for at in range(opening, len(clean)):
        char = clean[at]
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
            if not depth:
                return at, (commas + 1 if clean[opening + 1:at].strip() else 0)
        elif char == ',' and depth == 1:
            commas += 1
    return None


def _float_zeros(clean, opening, closing):
    """(start, end) of the trailing arguments of the call at `opening`..`closing` that spell a float zero."""
    found, end = [], closing
    while end > opening:
        depth, at = 0, end - 1
        while at > opening and (depth or clean[at] != ','):
            depth += (clean[at] in ')]}') - (clean[at] in '([{')
            at -= 1
        text = clean[at + 1:end]
        value = text.strip()
        if _FLOAT_ZERO.fullmatch(value):
            start = at + 1 + text.index(value)
            found.append((start, start + len(value)))
        elif value != '0':
            break
        end = at
    return found


def _literal(value):
    return value if isinstance(value, str) else (hex(value) if value > 9 else str(value))


def _widen(part, callee, extra):
    """The edit that gives the callee's prototype in the source `extra` more `s32` parameters, when it names some."""
    hit = re.search(rf'(?m)^[^\n(){{}};]*?(?<![\w.>]){callee}\s*\(([^)]*)\)\s*;', part.clean[:part.opening])
    if not hit or not hit[1].strip() or hit[1].strip() == 'void' or '...' in hit[1]:
        return []
    return [(hit.end(1), hit.end(1), ', s32' * extra)]


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    spans = []
    constants = target_constants(asm)
    for callee, words in target_words(asm).items():
        total = max(words, default=-1) + 1
        for call in re.finditer(rf'(?<![\w.>]){callee}\s*\(', part.clean[part.opening:part.end]):
            found = _arguments(part.clean, part.opening + call.end() - 1)
            if not found:
                continue
            closing, count = found
            for start, end in _float_zeros(part.clean, part.opening + call.end() - 1, closing):
                index = _arguments(part.clean[:start] + ')', part.opening + call.end() - 1)[1] - 1
                if index >= 4 and words.get(index) == 'zero':
                    spans.append((start, end, '0'))
            if 4 <= count < total:
                missing = [words[index] == 'zero' and '0' or constants.get(callee, {}).get(index) for index in
                           range(count, total)]
                if all(value is not None for value in missing):
                    spans.append((closing, closing, ''.join(f', {_literal(value)}' for value in missing)))
                    spans += [span for span in _widen(part, callee, total - count) if span not in spans]
    if not spans:
        return []
    result = [(FAMILY, edit(source, spans))]
    clean = _blank(result[0][1])
    pads = [hit for hit in re.finditer(rf'(?m)^[ \t]*volatile\s+(?:unsigned\s+)?{IDENT}\s+({IDENT})\s*;[ \t]*\n', clean)
            if len(re.findall(rf'\b{hit[1]}\b', clean)) == 1]
    if pads:
        result.append((FAMILY, edit(result[0][1], [(hit.start(), hit.end(), '') for hit in pads])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
