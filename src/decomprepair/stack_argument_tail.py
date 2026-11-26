"""Trailing zero arguments a call lacks, read from the words the target stores above its register arguments.

m2c and hand-written drafts stop short on a callee declared `()` that takes a long run of arguments: the target stores
each one past the fourth at `0x10($sp)`, `0x14($sp)`, ... before the `jal`, and a call two arguments short compiles a
frame 8 bytes smaller, so every saved register's slot and the epilogue differ too. On a KMC 2.7.2 `-O1` function the
18-argument call was written with 16 (233, 18 stack rows); the two zeros were most of the way to the match. An
earlier draft had hidden the frame with an unused `volatile` local, so a second child also drops such a local.

Only zeros are appended: the target says which words are zero, and nothing here guesses any other value."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'stack_argument_tail'
FAMILIES = (FAMILY,)
MAXIMUM = 40  # words
_CALL = re.compile(rf'\bjal\s+({IDENT})')
_BRANCH = re.compile(r'\b(?:jalr?|jr|j|b[a-z0-9]*)\s')
_STORE = re.compile(r'\bsw\s+\$(\w+)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')


def target_words(asm):
    """{callee: {argument index: stored register}} for the words each call's block puts at 0x10($sp) and above,
    counted only while they are contiguous."""
    lines = [line for line in asm.splitlines() if line.strip() and not line.rstrip().endswith(':')]
    found = {}
    for index, line in enumerate(lines):
        call = _CALL.search(line)
        if not call:
            continue
        stores = {}
        block = lines[index + 1:index + 2]
        for earlier in reversed(lines[:index]):
            if _BRANCH.search(earlier):
                break
            block.append(earlier)
        for text in block:
            hit = _STORE.search(text)
            if hit:
                stores.setdefault(int(hit[2], 0), hit[1])
        words = {}
        offset = 0x10
        while offset in stores and len(words) < MAXIMUM:
            words[offset // 4] = stores[offset]
            offset += 4
        if len(words) > len(found.get(call[1], {})):
            found[call[1]] = words
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


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    spans = []
    for callee, words in target_words(asm).items():
        total = max(words, default=-1) + 1
        for call in re.finditer(rf'(?<![\w.>]){callee}\s*\(', part.clean[part.opening:part.end]):
            found = _arguments(part.clean, part.opening + call.end() - 1)
            if not found:
                continue
            closing, count = found
            if 4 <= count < total and all(words[index] == 'zero' for index in range(count, total)):
                spans.append((closing, closing, ', 0' * (total - count)))
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
