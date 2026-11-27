"""A temporary the game computed with its siblings at the head, assigned instead inside the `if` that first uses it.

m2c puts `temp_s2 = (D_800B8532 - D_800B852C) >> 7;` where the value is first used, inside the guard of a loop; the
game computed the four range limits one after the other before it read a table and tested the loop's count. The
scheduler orders loads by the source's statement order and the allocator numbers pseudos by first set, so the late
assignment puts its two global loads after the table loads, and the register that holds the shared subtrahend is
reused (`$a2` where the target has `$v0`, the `sra` in another place). An N64 object search (KMC GCC 2.7.2 `-O1 -g`,
four limits of the form `(s32) (G - H) >> 7`, the fourth inside `if (count > 0) {`): 595 -> 200 on this alone, and exact
together with `loaded_pointee_width`'s byte count.

A site is an assignment `L = E;` in a block nested only in `if` / `else` blocks of a top-level statement, where `L` is a
local that nothing else assigns and `E` reads only integer globals and literals (no call, no assignment, no
dereference of a pointer), and an earlier top-level statement `K = E';` has the same shape (the same operators, casts and
literals with the names and numbers abstracted): the assignment moves to just after the last such sibling. It crosses
only text that cannot change what `E` reads or make it fault: no call, no `++`/`--`, and every assignment in it goes to a
plain local that `E` does not read. One child per site, and one with every site.
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import edit, view

FAMILY = 'guarded_assignment_head_hoist'
FAMILIES = (FAMILY,)
LIMIT = 6
_TYPES = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'char', 'short', 'long', 'unsigned', 'signed'}
_EXTERN = re.compile(r'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>(?:(?:unsigned|signed)[ \t]+)?[A-Za-z_]\w*)[ \t]+'
                     r'(?P<name>[A-Za-z_]\w*)[ \t]*;')
_ASSIGN = re.compile(r'(?P<lhs>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<rhs>[^;{}]+);\Z')
_CALL = re.compile(r'\b(?!(?:if|while|for|switch|return|else)\b)[A-Za-z_]\w*\s*\(')
_STORE = re.compile(r'(?<![=!<>])=(?!=)')
_OPENING_IF = re.compile(r'\s*(?:else\b|if\b)')


def _scalars(text):
    return {hit['name'] for hit in _EXTERN.finditer(text) if hit['type'].split()[-1] in _TYPES}


def _shape(rhs, scalars):
    """The expression with its names and numbers abstracted, or None when it reads anything but integer globals."""
    if _CALL.search(rhs) or re.search(r'\+\+|--|[=\[\]]|->|\.|&(?!&)', rhs):
        return None
    for word in re.findall(r'[A-Za-z_]\w*', rhs):
        if word not in scalars and word not in _TYPES:
            return None
    rhs = re.sub(r'\b0[xX][0-9A-Fa-f]+\b|\b\d+\b', 'N', rhs)
    return re.sub(r'\s+', '', re.sub(r'\b(?!(?:%s)\b)[A-Za-z_]\w*' % '|'.join(sorted(_TYPES)), 'I', rhs))


_DECLARATION = re.compile(r'\s*(?:(?:unsigned|signed|const|volatile|struct|union)\s+)*[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*?\s+'
                          r'(?P<decls>\*{0,3}\s*[A-Za-z_]\w*(?:\s*,\s*\*{0,3}\s*[A-Za-z_]\w*)*)\s*;')


def _locals(clean, opening):
    """Names of the plain declarations (`T a, *b;`) that open the function body, and the names of the ones of an
    integer type."""
    names, integers, at = set(), set(), opening + 1
    while found := _DECLARATION.match(clean, at):
        kind = clean[at:found.start('decls')].split()
        for decl in found['decls'].split(','):
            decl = decl.strip().lstrip('*').strip()
            names.add(decl)
            if '*' not in found['decls'] and kind and kind[-1] in _TYPES:
                integers.add(decl)
        at = found.end()
    return names, integers


def _crossing_is_safe(text, locals_, reads):
    if _CALL.search(text) or re.search(r'\+\+|--', text):
        return False
    for chunk in re.split(r'[;{}]', text):
        hit = _STORE.search(chunk)
        while hit:
            left = chunk[:hit.start()].rstrip()
            left = re.sub(r'[-+*/%&|^]+$|<<$|>>$', '', left).rstrip()
            word = re.search(r'(?<![\w.>\]])([A-Za-z_]\w*)\Z', left)
            if not word or word[1] not in locals_ or word[1] in reads or left.endswith((')', ']')):
                return False
            hit = _STORE.search(chunk, hit.end())
    return True


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end) or {}
    scalars = _scalars(clean[:part.opening]) | _scalars(re.sub(r'/\*.*?\*/|//[^\n]*', '', header or '', flags=re.S))
    locals_, integers = _locals(clean, part.opening)
    top = statements(clean, part.opening + 1, part.end - 1)
    siblings = []
    for begin, end in top:
        hit = _ASSIGN.match(clean[begin:end])
        shape = hit and hit['lhs'] in integers and _shape(hit['rhs'], scalars)
        if shape:
            siblings.append((end, shape))
    found = []
    for begin, end in top:
        if '{' not in clean[begin:end]:
            continue
        before = [(stop, shape) for stop, shape in siblings if stop <= begin]
        for opening in sorted(o for o in pairs if begin <= o < end):
            for low, high in statements(clean, opening + 1, pairs[opening]):
                hit = _ASSIGN.match(clean[low:high])
                if not hit or hit['lhs'] not in integers:
                    continue
                shape = _shape(hit['rhs'], scalars)
                partners = [stop for stop, other in before if other == shape]
                if not shape or not partners:
                    continue
                if len(re.findall(rf'\b{hit["lhs"]}\b\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[part.opening:part.end])) != 1:
                    continue
                if any(not (_OPENING_IF.match(clean[max(clean.rfind(c, 0, o) for c in ';{}') + 1:o])
                            if begin <= o < low < c else True)
                       for o, c in pairs.items() if begin <= o < low < c):
                    continue
                if not _crossing_is_safe(clean[partners[-1]:low], locals_, set(re.findall(r'\w+', hit['rhs']))):
                    continue
                found.append((partners[-1], low, high))
    seen, sites = set(), []
    for site in sorted(found):
        if site[1] not in seen:
            seen.add(site[1])
            sites.append(site)

    def moved(chosen):
        edits = []
        for after, low, high in chosen:
            line = source.rfind('\n', 0, low) + 1
            start = line if not source[line:low].strip() else low
            stop = high + 1 if source[high:high + 1] == '\n' else high
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, after) + 1:after])[0]
            edits += [(start, stop, ''), (after, after, f'\n{indent}{source[low:high]}')]
        return edit(source, edits)

    result = [(FAMILY, moved([site])) for site in sites]
    if len(sites) > 1:
        result.insert(0, (FAMILY, moved(sites)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
