"""m2c's display-list draft whose cursor global stands for a value it no longer holds, written as the SDK's macros.

m2c tracks a register that still holds an earlier value of the cursor by the global's name. After `gCursor = temp + 8;
gCursor = temp + 0x10;` its `M2C_FIELD(gCursor, s32 *, 8) = ..` means the value the cursor had at the run's first
read, not the one just stored, so the draft writes a word two commands too far and `gbi_macro_commands` finds no run at
all. The autopilot's draft also types those accesses as records of `mHEX` members (read back here as `M2C_FIELD`s) and
advances the cursor with `gCursor += 8`. `gbi_stale_cursor` reads every use of the cursor since the run's first read as
that read (and writes `+=` against it), then hands the source to `gbi_macro_commands`. One variant also keeps the
printed meaning, for a draft where the global was right.

`gbi_stale_cursor_loops` finishes the loops around those commands, all in one child because each step alone helps only
in part: m2c's second webs (`var_t1_2`) become the first (`var_t1`), a parameter a loop body reads is copied into a
local beside the copy of the parameter the loop steps (`var_t1 = arg0; arg1_copy = arg1;`), a guarded loop's starting
values move below the commands that follow them, and `if (n != 0) { do { ..; i += 1; } while (i < n); }` with `i`
starting at 0 and `n` unsigned is the `for` it came from.

Measured on a 114-instruction N64 dotted-bar drawer (two rows of fill rectangles, SN GCC 2.8.1 `-mfp64`): saved draft
3895, the macros 565, byte-identical with the loops. One function."""
import re

from . import gbi_macro_commands as macros
from .arm_block_support import brace_pairs
from .csource import _blank
from .display_cursor_record_repairs import _statements
from .integer_repair_support import IDENT, edit, view
from .returned_gfx_cursor import _plain_fields

FAMILY = 'gbi_stale_cursor'
LOOPS_FAMILY = 'gbi_stale_cursor_loops'
FAMILIES = (FAMILY, LOOPS_FAMILY)
MACRO = r'g(?:DP|SP)\w+|gRawWords'


def _reads(source, name, cursor, kind, stale):
    """`source` with the cursor's uses read through a local: the run's first read (m2c's own, or one added). With
    `stale` that local keeps standing for the global until a branch or a call; without it, until the next write."""
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    mention = re.compile(rf'(?<![\w.>])\b{re.escape(cursor)}\b')
    write = re.compile(rf'{re.escape(cursor)}\s*(?P<op>[+-])?=(?!=)\s*')
    read = re.compile(rf'(?P<x>{IDENT})\s*=\s*{re.escape(cursor)}\s*;\Z')
    edits, decls, current, fresh, previous = [], [], None, False, None

    def declare(at):
        local = next(n for n in (f'_cur{k}' for k in range(1, 1000)) if n not in clean and n not in decls)
        decls.append(local)
        line = clean.rfind('\n', 0, at) + 1
        edits.append((at, at, f'{local} = {cursor};\n{re.match(r"[ \t]*", clean[line:at])[0]}'))
        return local

    for a, b in _statements(clean, start, end):
        text = clean[a:b]
        if previous is not None and re.search(r'[{}]', clean[previous:a]):
            current = None
        previous = b
        if hit := write.match(text):
            if hit['op']:
                if current is None or not fresh:
                    current = declare(a)
                edits.append((a, b, f'{cursor} = {current} {hit["op"]} {source[a + hit.end():b - 1].strip()};'))
            else:
                found = list(mention.finditer(text, hit.end()))
                if found:
                    current = current or declare(a)
                    edits += [(a + m.start(), a + m.end(), current) for m in found]
            fresh = False
            if not stale:
                current = None
            continue
        if macros.CALL.search(text):
            current = None
        if hit := read.match(text):
            current, fresh = hit['x'], True
            continue
        if mention.search(text):
            if current is None:
                current, fresh = declare(a), True
            edits += [(a + m.start(), a + m.end(), current) for m in mention.finditer(text)]
    if not edits:
        return source
    if decls:
        edits.append((start, start, ''.join(f'\n    {kind} *{d};' for d in decls)))
    return edit(source, edits)


def _unused_reads(source):
    """Drop the declarations of added locals the macros left nothing to use."""
    for local in set(re.findall(r'\b_cur\d+\b', source)):
        if len(re.findall(rf'\b{local}\b', source)) == 1:
            source = re.sub(rf'\n[ \t]*\w+ \*{local};', '', source)
    return source


def _commands(source, name, header):
    """[macro rewrite] of the draft with the cursor read the stale way, then the printed way."""
    plain = _plain_fields(source, name) or source
    part = view(plain, name)
    if not part:
        return []
    pointers = [(p['name'], p['type']) for p in macros.POINTER.finditer(part.clean[:part.opening])]
    if not pointers:
        return []
    known = {child for _, child in macros.variants(source, name, header)}
    out = []
    for stale in (True, False):
        text = plain
        for cursor, kind in pointers:
            text = _reads(text, name, cursor, kind, stale)
        if text == source:
            continue
        child = next((c for family, c in macros._variants(text, name, header) if family == macros.FAMILY), None)
        if child and child not in known:
            child = _unused_reads(child)
            if child not in out:
                out.append(child)
    return out


# ---- loops ------------------------------------------------------------------------------------------------------

def _merge_webs(source, name):
    """`var_t1_2` written as `var_t1`, when both are declared with one type."""
    part = view(source, name)
    if not part:
        return source
    declared = {m['n']: m['t'] for m in re.finditer(
        rf'(?m)^[ \t]*(?P<t>{IDENT})\s+(?P<n>var_\w+)\s*;', part.clean[part.opening:part.end])}
    for web, kind in declared.items():
        first = re.fullmatch(r'(?P<base>var_[a-z]+\d*)_\d+', web)
        if first and declared.get(first['base']) == kind:
            source = re.sub(rf'\n[ \t]*{kind}\s+{web}\s*;', '', source)
            source = re.sub(rf'\b{web}\b', first['base'], source)
    return source


def _parameters(source, name):
    part = view(source, name)
    head = part and list(re.finditer(rf'\b{re.escape(name)}\s*\(([^()]*)\)', part.clean[:part.opening]))
    if not head:
        return {}
    found = {}
    for piece in head[-1][1].split(','):
        words = piece.split()
        if len(words) >= 2 and re.fullmatch(IDENT, words[-1]):
            found[words[-1]] = ' '.join(words[:-1])
    return found


def _copy_parameters(source, name):
    """In each loop that steps a copy `v = p;` of one parameter, the other parameters its body reads copied the same
    way. A parameter the function assigns or takes the address of is left alone, and so are loop bounds."""
    part = view(source, name)
    if not part:
        return source
    parameters = _parameters(source, name)
    body = part.clean[part.opening:part.end]
    fixed = {p for p in parameters
             if not re.search(rf'(?:&\s*{p}\b|\b{p}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\b{p}\s*(?:\+\+|--))', body)}
    pairs = brace_pairs(part.clean, part.opening, part.end) or {}
    edits, copied, taken = [], {}, set()
    for loop in re.finditer(r'\bdo\s*\{', part.clean[:part.end]):
        if loop.start() < part.opening:
            continue
        opening = loop.end() - 1
        closing = pairs.get(opening)
        if closing is None:
            continue
        inside = part.clean[opening:closing]
        stepped = set(re.findall(rf'\b({IDENT})\s*\+=', inside))
        seeds = [m for m in re.finditer(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*(?P<p>{IDENT})\s*;', part.clean[:loop.start()])
                 if m.start() > part.opening and m['v'] in stepped and m['p'] in parameters]
        if not seeds:
            continue
        seed = max(seeds, key=lambda m: m.start())
        new = []
        for p in parameters:
            uses = [m for m in re.finditer(rf'(?<![\w.>])\b{p}\b', inside)]
            if p == seed['p'] or p not in fixed or not uses:
                continue
            local = copied.setdefault(p, f'{p}_copy')
            if re.search(rf'\b{local}\b', part.clean):
                return source
            new.append(f'{local} = {p};')
            edits += [(opening + m.start(), opening + m.end(), local) for m in uses
                      if (opening + m.start()) not in taken]
            taken.update(opening + m.start() for m in uses)
        if new:
            line = part.clean.rfind('\n', 0, seed.start()) + 1
            indent = re.match(r'[ \t]*', part.clean[line:])[0]
            edits.append((seed.end(), seed.end(), ''.join(f'\n{indent}{text}' for text in new)))
    if not edits:
        return source
    declarations = ''.join(f'\n    {parameters[p]} {local};' for p, local in copied.items())
    edits.append((part.opening + 1, part.opening + 1, declarations))
    return edit(source, edits)


MOVED = re.compile(
    rf'(?P<set>(?:\n[ \t]*{IDENT}\s*=\s*(?:{IDENT}|\d+)\s*;)+)'
    rf'(?P<commands>(?:\n[ \t]*(?:{MACRO})\s*\([^;{{}}]*\);)+)(?=\s*if\s*\()')


def _below_commands(source):
    """A guarded loop's starting values moved below the commands between them and its guard, when no command names
    them."""
    def move(hit):
        names = re.findall(rf'({IDENT})\s*=\s*(?:{IDENT}|\d+)\s*;', hit['set'])
        if any(re.search(rf'\b{n}\b', hit['commands']) for n in names):
            return hit[0]
        return hit['commands'] + hit['set']
    return MOVED.sub(move, source)


GUARDED = re.compile(
    rf'\n(?P<indent>[ \t]*)if\s*\(\s*(?P<n>{IDENT})\s*(?:!=|>)\s*0\s*\)\s*\{{\s*do\s*\{{(?P<body>[^{{}}]*)\}}\s*'
    rf'while\s*\(\s*(?P<i>{IDENT})\s*<\s*(?P=n)\s*\)\s*;\s*\}}')


def _for_loops(source, name):
    parameters = _parameters(source, name)
    clean = _blank(source)
    edits = []
    for hit in GUARDED.finditer(clean):
        i, n = hit['i'], hit['n']
        unsigned = parameters.get(n, '') in ('u32', 'unsigned', 'unsigned int')
        if not unsigned or not re.search(rf'\b{i}\s*=\s*0\s*;', clean[:hit.start()]):
            continue
        body = source[hit.start('body'):hit.end('body')]
        step = re.search(rf'\n[ \t]*(?:{i}\s*\+=\s*1|{i}\+\+)\s*;', body)
        if not step:
            continue
        body = (body[:step.start()] + body[step.end():]).rstrip()
        if re.search(rf'\b{i}\b', body):
            continue
        body = body.replace('\n    ', '\n')
        indent = hit['indent']
        edits.append((hit.start(), hit.end(), f'\n{indent}for (; {i} < {n}; {i}++) {{{body}\n{indent}}}'))
    return edit(source, edits) if edits else source


def loops(source, name):
    """The finished loops, then the webs and parameter copies alone; nothing when the source runs no macro."""
    part = view(source, name)
    if not part or not re.search(rf'\b(?:{MACRO})\s*\(', part.clean[part.opening:part.end]):
        return []
    copies = _copy_parameters(_merge_webs(source, name), name)
    if copies == source or '_copy' not in copies:
        return []
    finished = _for_loops(_below_commands(copies), name)
    return list(dict.fromkeys(text for text in (finished, copies) if text != source))


def variants(source, name, header=''):
    children = [(FAMILY, child) for child in _commands(source, name, header)]
    finished = []
    for base in [child for _, child in children[:1]] + [source]:
        finished += [(LOOPS_FAMILY, child) for child in loops(base, name)]
    return children + list(dict.fromkeys(finished))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',),
          'order': 40}
