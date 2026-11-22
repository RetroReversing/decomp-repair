"""A table of rows addressed as `table[row][column]`, where m2c walked a word and an address.

m2c sees `extern s32 D_80100000;` (one word, the only thing the code loads from it) and writes a row-major table as
pointer arithmetic: `p = (&D) + row * 7; p += column; ... *p` for a count the game keeps per (row, column), or
`p = &D; p += temp; p += column;` with `temp = row * 7;` kept for a second table, whose bytes m2c reads as
`*(s32 *)(column * 4 + (temp * 4 + base))` with `base = D2;` and `extern u8 D2[];`. The game wrote both as
`s32 D[][7]` and `D[row][column]`. On a 374-instruction KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) function
the three accesses were 35 points (seven register rows: the pointer walk adds `row * 28 + base` to the scaled column
the other way round, and gives the sum a register of its own), and subscripted rows were exact, with the walking
locals and the byte table's staging gone. The edits only pay off together: the declarations of both tables have to
agree on the row length, and the byte table's access has to read the same row product, so one child makes every
change at once; then one child per table.

The pointer is never kept (`p = &D[row][column];` scored 2215 where the plain subscript scored 0: the early address
hoists its row product above other work): each read or write through it becomes the subscript, and only when every
use of it is in the very next statement (an `if` condition or one statement), so the row and column are read at the
same point and nothing between them can store. Nothing is offered when a use of a table cannot be rewritten.
The register explanation (the sum's operand order in `local-alloc.c`) is a hypothesis; the exact judge decides.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'row_major_table'
FAMILIES = (FAMILY,)

WORDS = ('s32', 'u32', 'int')
BYTES = ('u8', 's8', 'char', 'unsigned char')
STOP = r'[^;{}]'


def _operand(text):
    """True when `text` is one operand (an identifier, a number, a parenthesised or dereferenced group)."""
    text = text.strip()
    if re.fullmatch(rf'{IDENT}|{NUMBER}', text):
        return True
    if text.startswith('(') and close(text, 0) == len(text):
        return True
    return text.startswith('*(') and close(text, 1) == len(text)


def _externs(clean):
    """The scalar words and the byte arrays declared outside functions: {name: (start, end)} each."""
    words, arrays = {}, {}
    for hit in re.finditer(rf'(?m)^[ \t]*extern\s+(?:{"|".join(WORDS)})\s+(?P<g>{IDENT})\s*;[ \t]*$', clean):
        words[hit['g']] = hit.span()
    for hit in re.finditer(rf'(?m)^[ \t]*extern\s+(?:{"|".join(BYTES)})\s+(?P<g>{IDENT})\s*\[\s*\]\s*;[ \t]*$', clean):
        arrays[hit['g']] = hit.span()
    return words, arrays


def _statement_end(clean, at, limit):
    """The position past the statement starting at `at`: an `if (...)` runs to the end of its condition."""
    hit = re.compile(r'if\s*\(').match(clean, at)
    if hit:
        return close(clean, hit.end() - 1)
    end = clean.find(';', at, limit)
    return end + 1 if end >= 0 and '{' not in clean[at:end] else None


def _reads(clean, after, pointer, limit, skippable):
    """The spans of every `*pointer` / `(*pointer)` after `after` when they all lie in the very next statement and nothing
    else names the pointer until it is assigned again; else None. `skippable` names may be assigned in between."""
    at = after
    while True:
        while at < limit and clean[at].isspace():
            at += 1
        hit = re.compile(rf'(?P<l>{IDENT})\s*=\s*(?P<r>{IDENT})\s*;').match(clean, at)
        if hit and hit['r'] in skippable:
            at = hit.end()
            continue
        break
    end = _statement_end(clean, at, limit)
    if not end:
        return None
    again = re.compile(rf'(?<![\w.>]){re.escape(pointer)}\s*=(?!=)').search(clean, after, limit)
    region = again.start() if again else limit
    word = re.escape(pointer)
    spans = [(at + hit.start(), at + hit.end())
             for hit in re.finditer(rf'\(\s*\*\s*{word}\s*\)|\*\s*{word}\b', clean[at:end])]
    for begin, _ in spans:
        lead = clean[:begin].rstrip()
        if lead and (lead[-1].isalnum() or lead[-1] in '_)]'):
            return None
    named = [after + hit.start() for hit in re.finditer(rf'\b{word}\b', clean[after:region])]
    covered = sum(len(re.findall(rf'\b{word}\b', clean[a:b])) for a, b in spans)
    return spans if spans and len(named) == covered else None


def _product_defs(clean, part):
    """{temp: (row identifier, stride, span)} for `temp = row * 7;` assigned once in the function."""
    found, seen = {}, {}
    body = clean[part.opening:part.end]
    for hit in re.finditer(rf'(?<![\w.>])(?P<t>{IDENT})\s*=\s*(?P<a>{IDENT})\s*\*\s*(?P<k>{NUMBER})\s*;', body):
        found[hit['t']] = (hit['a'], int(hit['k'].rstrip('uUlL'), 0), (part.opening + hit.start(), part.opening + hit.end()))
    for hit in re.finditer(rf'(?<![\w.>])(?P<t>{IDENT})\s*=(?!=)', body):
        seen[hit['t']] = seen.get(hit['t'], 0) + 1
    return {t: value for t, value in found.items() if seen.get(t) == 1}


def _assigned_between(clean, name, start, end):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b'
                     rf'|\b{re.escape(name)}\s*(?:\+\+|--)', clean[start:end]) is not None


def _scan(part, words, arrays):
    """({table: row length}, [(table, start, end, text)]): every access that becomes a subscript, or None when a table
    would need two row lengths."""
    clean, limit, first = part.clean, part.end, part.opening
    products = _product_defs(clean, part)
    strides, edits = {}, []
    scope = clean[first:limit]

    def add(table, k, rows):
        if strides.setdefault(table, k) != k:
            raise ValueError(table)
        edits.extend((table, *row) for row in rows)

    try:
        for hit in re.finditer(
                rf'(?P<p>{IDENT})\s*=\s*\(?\s*&\s*(?P<g>{IDENT})\s*\)?\s*\+\s*(?P<a>{STOP}+?)\s*\*\s*(?P<k>{NUMBER})\s*;'
                rf'\s*(?P=p)\s*\+=\s*(?P<b>{STOP}+?)\s*;', scope):
            start, end = first + hit.start(), first + hit.end()
            k = int(hit['k'].rstrip('uUlL'), 0)
            reads = _reads(clean, end, hit['p'], limit, set(arrays)) if hit['g'] in words and _operand(hit['a']) else None
            if reads and k >= 2:
                subscript = f"{hit['g']}[{hit['a'].strip()}][{hit['b'].strip()}]"
                add(hit['g'], k, [(start, end, '')] + [(a, b, subscript) for a, b in reads])
        for hit in re.finditer(
                rf'(?P<p>{IDENT})\s*=\s*&\s*(?P<g>{IDENT})\s*;\s*(?P=p)\s*\+=\s*(?P<t>{IDENT})\s*;'
                rf'\s*(?P=p)\s*\+=\s*(?P<b>{STOP}+?)\s*;', scope):
            start, end = first + hit.start(), first + hit.end()
            if hit['g'] not in words or hit['t'] not in products:
                continue
            row, k, span = products[hit['t']]
            reads = _reads(clean, end, hit['p'], limit, set(arrays))
            if reads and span[1] <= start and not _assigned_between(clean, row, span[1], end):
                subscript = f"{hit['g']}[{row}][{hit['b'].strip()}]"
                add(hit['g'], k, [(start, end, '')] + [(a, b, subscript) for a, b in reads])
        for hit in re.finditer(
                rf'\*\s*\(\s*(?:{"|".join(WORDS)})\s*\*\s*\)\s*\(\s*(?P<b>{STOP}+?)\s*\*\s*4\s*\+\s*\(\s*(?P<t>{IDENT})'
                rf'\s*\*\s*4\s*\+\s*(?P<base>{IDENT})\s*\)\s*\)', scope):
            start, end = first + hit.start(), first + hit.end()
            if hit['t'] not in products or not _operand(hit['b']):
                continue
            row, k, span = products[hit['t']]
            sets = list(re.finditer(rf'(?<![\w.>]){re.escape(hit["base"])}\s*=(?!=)\s*(?P<d>{IDENT})\s*;', scope))
            if len(sets) != 1 or sets[0]['d'] not in arrays or _assigned_between(clean, row, span[1], end):
                continue
            table = sets[0]['d']
            add(table, k, [(start, end, f"{table}[{row}][{hit['b'].strip()}]"),
                           (first + sets[0].start(), first + sets[0].end(), '')])
    except ValueError:
        return None
    return strides, edits


def _apply(source, strides, edits, words, arrays, chosen):
    pairs = sorted({(a, b, text) for table, a, b, text in edits if table in chosen})
    if not pairs or any(c < b for (_, b, _), (c, _, _) in zip(pairs, pairs[1:])):
        return None
    for table in chosen:
        start, end = words.get(table) or arrays[table]
        pairs.append((start, end, f'extern s32 {table}[][{strides[table]}];'))
    text = edit(source, sorted(pairs))
    # nothing may still name a converted table as a word or a byte array, nor leave a statement's carrier behind
    if any(re.search(rf'\b{re.escape(table)}\b(?!\s*\[)', _blank(text)) for table in chosen):
        return None
    return text


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b', part.body):
        return []
    words, arrays = _externs(part.clean)
    found = _scan(part, words, arrays) if words else None
    if not found or not found[0]:
        return []
    strides, edits = found
    out = []
    whole = _apply(source, strides, edits, words, arrays, set(strides))
    if whole:
        out.append((FAMILY, whole))
    if len(strides) > 1:
        for table in sorted(strides):
            single = _apply(source, strides, edits, words, arrays, {table})
            if single and single != whole:
                out.append((FAMILY, single))
    return out
