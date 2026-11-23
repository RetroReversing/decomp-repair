"""A loop's slot offset and slot pointer written back as the slot's index into the tables, one row at a time.

m2c names what the loop reads from a slot that stays the same while the loop runs: the slot's byte offset (`off = slot *
4;`), the address of its entry in one table (`ps = (T **)((char *)TAB + off);`, read as `*ps`) and its element of a table of
rows (`*(T **)((char *)ARR + k * 16 + off)`). The game indexed the tables (`TAB[slot]`, `ARR[k][slot]`) and let the loop
pass hoist what is invariant, and the loop pass hoists the offset into one register that both users share (`sll $s6, $s3,
2` once, `addu $s4, $s6, $s7` for the entry, `addu $v0, $s6, $v0` in the loop) where the named locals gave each its own
pseudo, and where the byte sum `ARR + k * 16 + slot * 4` did not hoist at all. In a 443-instruction KMC gcc 2.7.2 display-state
updater (`-G0 -mips3 -mgp32 -mfp32 -O2`) the three rewrites are one step: each alone was worse (the entry as `TAB[slot]` with
the byte sum 715, the byte sum alone 205) and together they were exact (365 -> 0 with the other families of its match).

    off = slot * 4;  ps = (T **)((char *)TAB + off);  ...  *ps ... *(T **)((char *)ARR + k * 16 + off)
->  ... TAB[slot] ... ARR[k][slot]                    and   `extern T *ARR[];` is `extern T *ARR[][4];`

Both the pointer and the row uses are offered together as one child; with no row use the pointer alone. The offset local
is `X * S` (one assignment, `X` a name), the pointer local one assignment of `(T *)((char *)TAB + off)` or `off + &TAB`,
read only as `*ps`, and the row table `extern T ARR[];` (unsized) read only through the byte sum. A candidate for the exact
judge, never a verdict.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'slot_row_index'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _statement_line(source, start, end):
    """The span to delete for the statement at start:end: its whole line when nothing else is on it."""
    left = source.rfind('\n', 0, start) + 1
    right = source.find('\n', end)
    right = len(source) if right < 0 else right + 1
    if not source[left:start].strip() and not source[end:right].strip():
        return left, right
    return start, end


def _names(body, name):
    """The mentions of `name` in the body that are not its declaration."""
    declared = re.compile(rf'(?m)^[ \t]*[\w ]+?[ \t]+\**[ \t]*{re.escape(name)}[ \t]*;')
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', body)
            if not declared.match(body, body.rfind('\n', 0, m.start()) + 1)]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    body = clean[opening:end]
    out = []
    for offset in re.finditer(rf'(?<![\w.>])(?P<off>{IDENT})\s*=(?!=)\s*(?P<x>{IDENT})\s*\*\s*(?P<s>{NUM})\s*;', body):
        off, x, scale = offset['off'], offset['x'], int(offset['s'], 0)
        assigned = len(re.findall(rf'(?<![\w.>]){off}\s*=(?!=)', body))
        loop = re.search(r'\b(?:for|while|do)\b', body[offset.end():])
        if assigned != 1 or not loop:
            continue
        edits = [_statement_line(source, opening + offset.start(), opening + offset.end())]
        replacements = []
        pointer = re.search(rf'(?<![\w.>])(?P<ps>{IDENT})\s*=(?!=)\s*(?:\(\s*[\w ]+?\s*\*+\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P<tab>{IDENT})\s*\+\s*{off}\s*\)'
                            rf'|{off}\s*\+\s*&\s*(?P<tab2>{IDENT}))\s*;', body[offset.end():])
        tab = None
        if pointer:
            ps, tab = pointer['ps'], pointer['tab'] or pointer['tab2']
            start = opening + offset.end() + pointer.start()
            uses = _names(body, ps)
            deref = [(m.start(), m.end()) for m in re.finditer(rf'(?<![*\w)])\*\s*{ps}\b', body)
                     if any(use.start() == m.end() - len(ps) for use in uses)]
            if len(uses) != len(deref) + 1 or len(re.findall(rf'(?<![\w.>]){ps}\s*=(?!=)', body)) != 1:
                continue
            edits.append(_statement_line(source, start, start + pointer.end() - pointer.start()))
            replacements += [(opening + a, opening + b, f'{tab}[{x}]') for a, b in deref]
        rows = []
        for row in re.finditer(rf'\*\s*\(\s*(?P<t>[\w ]+?\s*\*+)\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P<arr>{IDENT})\s*\+\s*(?P<a>{IDENT})\s*\*\s*(?P<row>{NUM})\s*\+\s*{off}\s*\)', body):
            declared = re.search(rf'(?m)^[ \t]*extern\s+(?P<ty>[^;()\[\]]*?)\s*(?<![\w])(?P<arr>{re.escape(row["arr"])})\s*\[\s*\]\s*;', clean[:opening])
            width = int(row['row'], 0)
            squash = lambda text: re.sub(r'\s', '', text)
            if not declared or width % scale or squash(row['t']) != squash(declared['ty']) + '*':
                continue
            rows.append((row, declared, width // scale))
        mentions = len(_names(body, off))
        covered = 1 + (len(re.findall(rf'(?<![\w.>]){off}\b', body[pointer.start() + offset.end():pointer.end() + offset.end()])) if pointer else 0) + len(rows)
        if not pointer and not rows:
            continue
        if mentions != covered:
            continue
        arrays = {row['arr'] for row, _, _ in rows}
        if any(len(re.findall(rf'(?<![\w.>]){re.escape(arr)}\b', body)) != sum(row['arr'] == arr for row, _, _ in rows) for arr in arrays):
            continue
        for row, declared, length in rows:
            replacements.append((opening + row.start(), opening + row.end(), f'{row["arr"]}[{row["a"]}][{x}]'))
        shapes = {}
        for row, declared, length in rows:
            shapes[row['arr']] = (declared, length)
        for declared, length in shapes.values():
            replacements.append((declared.start(), declared.end(), re.sub(r'\[\s*\]\s*;', f'[][{length}];', declared.group(0))))
        text = source
        for a, b, new in sorted([(a, b, '') for a, b in edits] + replacements, reverse=True):
            text = text[:a] + new + text[b:]
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
