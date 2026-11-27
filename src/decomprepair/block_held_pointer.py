"""A scalar global the target reaches twice through one temporary register, written through a pointer local in that block.

`lui $a0, %hi(D_x); addiu $a0, $a0, %lo(D_x)` and then `lb $v0, 0x0($a0)` twice (or `lbu` and `sb` back to the same
address) is a pointer the source held: written as `D_x` at each use, KMC GCC 2.7.2 `-O1` addresses the global directly
(`lui $v0; lb $v0, %lo(D_x)($v0)`) each time. Written as `{ T *held = &D_x; ... *held ... }` around the statements that
use it, the address is built once. On a 1950-instruction N64 menu routine two such blocks took a candidate from 2580 to
0; `held_symbol_pointer` offers only addresses held in saved registers from the head of the function.

The target's assembly is the evidence: only a symbol whose address goes into a register that is then used with offset 0
at least twice is offered. It must be declared `extern T D_x;` (not volatile, not an array) and used by name alone.
Each block of the function that uses it is a child of its own, then every offered block together.
"""
import re

from .csource import _blank, find

FAMILY = 'block_held_pointer'
FAMILIES = (FAMILY,)
LIMIT = 8
_ID = r'[A-Za-z_]\w*'
_ADDRESS = re.compile(rf'lui\s+\$(\w+),\s*%hi\(({_ID})\)\s*\n(?:[^\n]*?\*/)?\s*addiu\s+\$\1,\s*\$\1,\s*%lo\(\2\)')
_WINDOW = 12  # instructions after the address in which its uses are counted


def _held_symbols(asm):
    found = []
    for hit in _ADDRESS.finditer(asm):
        register, symbol = hit[1], hit[2]
        if register.startswith('s') and register != 'sp':
            continue
        uses = 0
        for line in asm[hit.end():].split('\n')[1:_WINDOW + 1]:
            if re.search(rf'\b[ls][bhw]u?\s+\$\w+,\s*(?:0x0|0)?\(\${register}\)', line):
                uses += 1
            if re.search(rf'\bjal\b|^\.|\b(?!s[bhw]\b)[a-z][\w.]*\s+\${register}\s*,', line.split('*/')[-1].strip()):
                break
        if uses >= 2 and symbol not in found:
            found.append(symbol)
    return found


def _statements(clean, opening, closing):
    """The (start, end) of each statement directly inside the block `clean[opening:closing + 1]`."""
    out, depth, parens, start = [], 0, 0, opening + 1
    for position in range(opening + 1, closing):
        char = clean[position]
        if char in '([':
            parens += 1
        elif char in ')]':
            parens -= 1
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if not depth and not clean[position + 1:closing].lstrip().startswith(('else', 'while', ';')):
                out.append((start, position + 1))
                start = position + 1
        elif char == ';' and not depth and not parens:
            if not clean[position + 1:closing].lstrip().startswith('else'):
                out.append((start, position + 1))
                start = position + 1
    return out


def _after_labels(clean, start):
    hit = re.match(rf'(?:\s*(?:case\b[^:;]*|default\s*|{_ID}\s*):)*', clean[start:])
    return start + hit.end()


def _innermost(clean, opening, position):
    stack = []
    for index in range(opening, position):
        if clean[index] == '{':
            stack.append(index)
        elif clean[index] == '}' and stack:
            stack.pop()
    return stack[-1] if stack else None


def _closing(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        depth += {'{': 1, '}': -1}.get(clean[index], 0)
        if not depth:
            return index
    return None


def _runs(clean, opening, symbol):
    """(start, end) of the statement run, per block, that uses `symbol`."""
    blocks = {}
    for hit in re.finditer(rf'(?<![\w.>]){symbol}\b', clean[opening:]):
        position = opening + hit.start()
        block = _innermost(clean, opening, position)
        if block is not None:
            blocks.setdefault(block, []).append(position)
    runs = []
    for block, positions in blocks.items():
        closing = _closing(clean, block)
        if closing is None:
            continue
        hit = [(_after_labels(clean, a), b) for a, b in _statements(clean, block, closing)
               if any(a <= p < b for p in positions)]
        if not hit:
            continue
        start, end = hit[0][0], hit[-1][1]
        text = clean[start:end]
        # a declaration or a label inside the run would change meaning inside new braces
        if re.search(rf'(?m)^\s*(?:{_ID}\s+\**{_ID}\s*(?:=|;|\[)|case\b|default\s*:|{_ID}\s*:)', text):
            continue
        runs.append((start, end))
    return runs


def _build(source, picked):
    for start, end, symbol, kind in sorted(picked, reverse=True):
        body = re.sub(rf'(?<![\w.>]){symbol}\b', f'(*held_{symbol})', source[start:end])
        wrapped = f'\n{{\n{kind} *held_{symbol} = &{symbol};\n{body.strip()}\n}}'
        source = source[:start] + wrapped + source[end:]
    return source


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    picked = []
    for symbol in _held_symbols(asm):
        declared = re.search(rf'\bextern\s+((?:unsigned\s+|signed\s+)?{_ID})\s+{symbol}\s*;', clean)
        if not declared or declared[1] == 'volatile' or f'held_{symbol}' in clean:
            continue
        if re.search(rf'&\s*{symbol}\b|(?<![\w.>]){symbol}\s*(?:\.|\[|->)', clean[opening:span[1]]):
            continue
        picked += [(start, end, symbol, declared[1]) for start, end in _runs(clean, opening, symbol)]
    apart = []  # blocks that don't overlap, for the combined child
    for item in sorted(picked):
        if not apart or item[0] >= apart[-1][1]:
            apart.append(item)
    out = [(FAMILY, _build(source, [item])) for item in picked[:LIMIT]]
    if len(apart) > 1:
        out.insert(0, (FAMILY, _build(source, apart)))
    return [item for item in out if item[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
