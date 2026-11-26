"""A do/while that walks a global table by a byte-offset cursor, written as the counter indexing the table.

m2c reads a global array through an offset it keeps beside the loop counter, `cursor = counter * size`, recomputed at
the bottom of every pass:

    acc = 0;
    cursor = 0 * 4;
    n = 0;
    do {
        temp = *(s32 *)(cursor + &TABLE);
        acc |= temp;
        n += 1;
        cursor = n * 4;
    } while (n < 8);

The game wrote the loop over the array: `for (i = 0; i < 8; i++) acc |= ((s32 *)&TABLE)[i];`. The cursor is a register
of its own in the m2c form (a multiply and an add per pass); the indexed read is one induction register the compiler
reduces itself, which is the target's pointer step. Measured with KMC gcc 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O2` on a
reader of an eight-word flag table, 125 -> 0; the counted `for`, the `do { ... i += 1; } while (i < 8)` spelling, and
each with the element read into a local first or in the `|=` itself were all exact.

`offset_cursor_indexed_do` keeps the `do` loop: the cursor's setup and its recomputation are removed and every read
`*(T *)(cursor + &G)` (also `&G + cursor`, `(u8 *)&G + cursor`, `M2C_FIELD(&G, T *, cursor)`) becomes
`((T *)&G)[counter]`. `offset_cursor_indexed_for` writes the same loop as `for (counter = A; counter < N; counter++)`
when the counter's setup is the statement just before the loop (the loop runs at least once: A < N).

What has to hold, or nothing is offered: the loop is `do { BODY counter += 1; cursor = counter * SIZE; } while (counter
< N);` (`counter++`, `++counter`, `cursor = counter << S`, a `(u32)` or `U` bound are the same), BODY has no nested
braces, `continue` or `goto`, the counter and the cursor are set by the statements just before the loop with the
cursor's value the counter's times SIZE, every use of the cursor anywhere is one of the table reads above, and SIZE is
the byte width of each read's type (so each element is `G[counter]` of that type), with no `&cursor` anywhere. The
cursor's local declaration, when it is a line of its own, goes too.

This module reads text only and never compiles or judges. The candidate is never a verdict: the judge decides."""
import re

from .csource import _blank, find

FAMILY_DO = 'offset_cursor_indexed_do'
FAMILY_FOR = 'offset_cursor_indexed_for'
FAMILIES = (FAMILY_DO, FAMILY_FOR)

ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|\d+)'
WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
         'float': 4, 's64': 8, 'u64': 8, 'f64': 8, 'double': 8}
TYPE = r'(?:(?:unsigned|signed|const|volatile)\s+)*(?:' + '|'.join(sorted(WIDTH, key=len, reverse=True)) + r')'
BYTE = r'(?:u8|s8|char)'
LOOP = re.compile(
    rf'\bdo\s*{{(?P<body>[^{{}}]*?)'
    rf'(?P<step>\b(?P<count>{ID})\s*(?:\+=\s*1|\+\+)\s*;|\+\+\s*(?P<count2>{ID})\s*;)\s*'
    rf'(?P<set>\b(?P<cursor>{ID})\s*=\s*\(?\s*(?P<again>{ID})\s*(?:\*\s*(?P<mul>{NUM})|<<\s*(?P<shift>{NUM}))\s*\)?\s*;)\s*'
    rf'}}\s*while\s*\(\s*(?:\(\s*(?:u32|s32|int|unsigned\s+int)\s*\)\s*)?(?P<test>{ID})\s*<\s*(?P<bound>{NUM})\s*[uU]?\s*\)\s*;'
)
STATEMENT = re.compile(rf'(?P<name>{ID})\s*=\s*(?P<value>[^;{{}}]+?)\s*;')
MAX_SETUP = 4


def _number(text):
    """The value of `A`, `A * B` or `A << B` with literal parts (and parentheses), else None."""
    text = text.strip()
    if text.startswith('(') and text.endswith(')'):
        return _number(text[1:-1])
    for op, fold in (('<<', lambda a, b: a << b), ('*', lambda a, b: a * b)):
        left, found, right = text.partition(op)
        if found:
            a, b = _number(left), _number(right)
            return None if a is None or b is None else fold(a, b)
    return int(text, 0) if re.fullmatch(NUM, text) else None


def _read(cursor):
    """A table read through `cursor`: the cast forms m2c writes, with the type, the table and a leading `&`."""
    one = rf'(?P<amp{{n}}>&\s*)?(?P<table{{n}}>{ID})'
    return re.compile(
        rf'\*\s*\(\s*(?P<type>{TYPE})\s*\*\s*\)\s*\(\s*(?:'
        rf'{cursor}\s*\+\s*{one.format(n=1)}|{one.format(n=2)}\s*\+\s*{cursor}|'
        rf'\(\s*{BYTE}\s*\*\s*\)\s*{one.format(n=3)}\s*\+\s*{cursor})\s*\)'
        rf'|M2C_FIELD\s*\(\s*(?P<amp4>&\s*)?(?P<table4>{ID})\s*,\s*(?P<type4>{TYPE})\s*\*\s*,\s*{cursor}\s*\)')


def _parts(hit):
    """(type, table, has `&`) of a read."""
    for n in '1234':
        if hit[f'table{n}']:
            return ' '.join((hit['type'] or hit['type4']).split()), hit[f'table{n}'], bool(hit[f'amp{n}'])


def _width(type_text):
    return WIDTH[type_text.split()[-1]]


def _setups(text):
    """The assignment statements that end `text`, last first: [(name, value, start, end)], at most MAX_SETUP."""
    found, end = [], len(text.rstrip())
    while len(found) < MAX_SETUP:
        head = text[:end]
        if not head.endswith(';'):
            break
        last = len(head) - 1  # the statement's own semicolon is not the previous statement's
        start = max(head.rfind(';', 0, last), head.rfind('{', 0, last), head.rfind('}', 0, last)) + 1
        piece = head[start:]
        hit = STATEMENT.fullmatch(piece.strip()) if piece.strip() else None
        if not hit:
            break
        lead = len(piece) - len(piece.lstrip())
        found.append((hit['name'], hit['value'], start + lead, end))
        end = start
    return found


def variants(source, name):
    if not (span := find(source, name)):
        return []
    clean = _blank(source)
    whole = clean[span[0]:span[1]]
    for hit in LOOP.finditer(clean, *span):
        count, cursor = hit['count'] or hit['count2'], hit['cursor']
        if count != hit['test'] or count != hit['again'] or cursor == count:
            continue
        size = int(hit['mul'], 0) if hit['mul'] else 1 << int(hit['shift'], 0)
        bound = int(hit['bound'], 0)
        body = clean[hit.start('body'):hit.end('body')]
        if size not in (1, 2, 4, 8) or re.search(r'\b(?:continue|goto)\b|{', body):
            continue
        reads = list(_read(re.escape(cursor)).finditer(clean, hit.start('body'), hit.end('body')))
        decl = re.search(rf'(?m)^[ \t]*(?:s32|u32|int|unsigned\s+int|s16|u16|s8|u8)\s+{re.escape(cursor)}\s*;[ \t]*\n', whole)
        uses = len(re.findall(rf'\b{re.escape(cursor)}\b', whole)) - bool(decl)
        if (not reads or any(_width(_parts(r)[0]) != size for r in reads) or uses != len(reads) + 2
                or re.search(rf'&\s*{re.escape(cursor)}\b', whole)):
            continue
        setups = _setups(clean[span[0]:hit.start()])
        by_name = {n: v for n, v, _a, _b in setups}
        if len(by_name) != len(setups) or count not in by_name or cursor not in by_name:
            continue
        start = _number(by_name[count])
        if start is None or start >= bound or _number(by_name[cursor]) != start * size:
            continue
        first = span[0] + setups[-1][2]
        if decl and span[0] + decl.end() > first:
            continue
        # the body, each read indexed by the counter
        text, offset = source[hit.start('body'):hit.end('body')], hit.start('body')
        for read in reversed(reads):
            type_text, table, amp = _parts(read)
            a, b = read.span()
            text = f'{text[:a - offset]}(({type_text} *){"&" if amp else ""}{table})[{count}]{text[b - offset:]}'
        before = source[:first]
        if decl:
            before = source[:span[0] + decl.start()] + source[span[0] + decl.end():first]
        pad = re.search(r'[ \t]*$', source[:hit.start()])[0]
        statements = [(n, source[span[0] + a:span[0] + b]) for n, _v, a, b in reversed(setups) if n != cursor]
        step = source[hit.start('step'):hit.end('step')]
        joined = ''.join(f'{s}\n{pad}' for _n, s in statements)
        out = [(FAMILY_DO, f'{before}{joined}do {{{text}{step}{source[hit.end("set"):hit.end()]}{source[hit.end():]}')]
        if statements[-1][0] == count:
            joined = ''.join(f'{s}\n{pad}' for n, s in statements if n != count)
            limit = source[hit.start('bound'):hit.end('bound')]
            loop = f'for ({count} = {by_name[count]}; {count} < {limit}; {count}++) {{{text.rstrip()}\n{pad}}}'
            out.append((FAMILY_FOR, f'{before}{joined}{loop}{source[hit.end():]}'))
        return out
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
