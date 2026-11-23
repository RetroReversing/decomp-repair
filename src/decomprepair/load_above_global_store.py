"""A pointer loaded by the statement after a global store, loaded before the store.

The compiler cannot move a load above a store to a global it may alias: `g = 0; p = *(void **)(arg + 0x68)...` reads
the pointer after the store, while the target read it between the two stores (`lw $v1, 0x68($s3)` before the
`lui/sw` of the second global). A developer who wrote the pointer into a local first (`actor = arg->actor; g = 0;
use(actor);`) gets that order. The local is one more name for a value the statement already read, so the proposal
adds one local, the load before the store, and the read in the statement turned into the local (785 -> 580 in one
557-instruction function, KMC GCC 2.7.2).

A proposal takes a statement that begins on the line after an assignment to an `extern` global (`G = ...;`, `G |= ...;`
with no call) and holds a read `*((T **) (((char *) P) + K))` or `*((T **) inline_fn(((char *) P), K))` of a pointer
field of a name `P` that the global's assignment does not mention; the read is written into a new local `T *` just
above the assignment. At most 6 proposals; the judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'load_above_global_store'
FAMILIES = (FAMILY,)
LIMIT = 6

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_TYPE = r'((?:[A-Za-z_]\w*\s+)*[A-Za-z_]\w*)\s*\*\s*\*'
_LOAD = re.compile(
    rf'\*\s*\(\s*\(\s*{_TYPE}\s*\)\s*(?:\(\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P<a>{_ID})\s*\)\s*\+\s*{_NUM}\s*\)'
    rf'|inline_fn\d*\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P<b>{_ID})\s*,\s*{_NUM}\s*\))\s*\)')
_STORE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<global>{_ID})\s*(?:[|&^+-]?=)(?!=)[^;\n]*;[ \t]*\n')
_KEYWORD = re.compile(r'\s*(?:if|while|for|do|switch|return|goto|else|case|default)\b')


def _externs(source):
    return set(re.findall(rf'(?m)^\s*extern\s+[^;(]*?\b({_ID})\s*(?:\[[^\]]*\])?\s*;', source))


def _statement_end(clean, at):
    depth = 0
    for position in range(at, len(clean)):
        depth += clean[position] in '([{'
        depth -= clean[position] in ')]}'
        if clean[position] == ';' and depth == 0:
            return position + 1
        if depth < 0:
            return None
    return None


def variants(source, name):
    """Proposals: a pointer field read hoisted above the global store before it."""
    part = view(source, name)
    if not part:
        return []
    names = _externs(source[:part.opening])
    if not names:
        return []
    out, used = [], 0
    for store in _STORE.finditer(part.clean, part.opening + 1, part.end):
        if store['global'] not in names or re.search(rf'\b{_ID}\s*\(', re.sub(r'\binline_fn\d*\s*\(', '(', store.group(0))):
            continue
        end = _statement_end(part.clean, store.end())
        if not end or _KEYWORD.match(part.clean, store.end()):
            continue
        seen = set()
        for load in _LOAD.finditer(part.clean, store.end(), end):
            text = part.clean[load.start():load.end()]
            base = load['a'] or load['b']
            if text in seen or re.search(rf'\b{base}\b', store.group(0)):
                continue
            seen.add(text)
            local = f'held{used}'
            kind = ' '.join(load.group(1).split()) + ' *'
            used += 1
            body = source[store.end():end]
            edits = [(store.start(), store.start(), f'{store["indent"]}{local} = {source[load.start():load.end()]};\n'),
                     (store.end(), end, body.replace(source[load.start():load.end()], local)),
                     (part.opening + 1, part.opening + 1, f'\n  {kind}{local};')]
            out.append((FAMILY, edit(source, edits)))
            if len(out) >= LIMIT:
                return list(dict.fromkeys(out))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
