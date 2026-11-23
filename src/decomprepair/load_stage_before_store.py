"""A load that follows a store in the source, read into a local before the store.

GCC 2.7.2 keeps a load behind an earlier store whenever it cannot prove the two apart (a store to a global scalar and a
load through a pointer in a register), so a source that stores first and reads after compiles in that order. A target
that read first has the load above the store, and the only source that writes it there names the loaded value in a local
that is set before the store. Two shapes of it were found by hand on a track-trigger state machine
(docs/learnings/function/identical-run-goto-state-machine-arms.md: 235 -> 175 and 235 -> 160):

`guarded_flag_load_stage`: a guarded table store whose index is a memory read follows a store.

    gChased = NULL;                              s32 staged = M;
    if (M) tab[M] = 1;                 ->        gChased = NULL;
                                                 if (staged) tab[staged] = 1;

(`M` is the same memory-read expression in the test, the index and the guard: m2c's repeated `if (x) tab[x] = v;`. The
local is `s32`: a narrower one adds the extension the target does not have.)

`global_pointer_load_stage`: a call whose argument dereferences a global pointer follows a store.

    state = 2;                                   { T *probe = gp;
    link(*gp, obj, 0);                 ->          state = 2;
                                                   link(*probe, obj, 0); }

(`gp` must be declared `extern T *gp;` in the source or the shared header.)
"""
import re

from .csource import _blank, find

FAMILIES = ('guarded_flag_load_stage', 'global_pointer_load_stage')

LIMIT = 8
_STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^\n;{}=]*[^=!<>\s])[ \t]*=(?!=)[^\n;]*;[ \t]*\n')
_CONTROL = re.compile(r'[ \t]*(?:if|for|while|else|return|case|switch|do|goto)\b')
_GUARDED = re.compile(
    r'(?m)^(?P<indent>[ \t]*)if[ \t]*\((?P<read>[^\n;{}]+)\)[ \t]*(?P<table>[A-Za-z_]\w*)\[(?P=read)\][ \t]*=[^\n;]*;[ \t]*\n')
_CALL = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<callee>[A-Za-z_]\w*)\((?P<before>[^\n;]*?)\*(?P<global>[A-Za-z_]\w*)\b(?P<after>[^\n;]*)\);[ \t]*\n')
_STAGED = 'staged'


def _declared(source, header, name):
    for text in (source, header or ''):
        m = re.search(r'\bextern\s+(?P<type>[A-Za-z_][\w\s]*?)\s*\*\s*' + re.escape(name) + r'\s*;', _blank(text))
        if m:
            return ' '.join(m['type'].split())
    return None


def _store_above(clean, at, source, header):
    """The match of a store to memory on the line just above `at`, or None. A bare name is memory when it is an
    `extern` of the source or the header; anything with a bracket, a dereference or a member is."""
    start = clean.rfind('\n', 0, max(at - 1, 0)) + 1
    m = _STORE.match(clean, start)
    if not m or m.end() != at or _CONTROL.match(m.group(0)):
        return None
    lhs = m['lhs'].strip()
    if re.fullmatch(r'[A-Za-z_]\w*', lhs):
        if not re.search(r'\bextern\b[^;]*\b' + re.escape(lhs) + r'\b', _blank(source) + _blank(header or '')):
            return None
    elif not re.search(r'[\[\]*(.]|->', lhs) or re.match(r'(?:register\s+|unsigned\s+|signed\s+|[usf](?:8|16|32|64)\s+|int\s+|long\s+)', lhs):
        return None
    return m


def variants(source, name, header=None):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = span[1]
    result = []
    for hit in _GUARDED.finditer(clean, opening + 1, end):
        store = _store_above(clean, hit.start(), source, header)
        if not store or hit['read'].strip() in store.group(0):
            continue
        new = source[hit.start():hit.end()].replace(hit['read'], _STAGED)
        text = (source[:store.start()] + f'{store["indent"]}s32 {_STAGED} = {hit["read"].strip()};\n' +
                source[store.start():hit.start()] + new + source[hit.end():])
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILIES[0], text))
    for hit in _CALL.finditer(clean, opening + 1, end):
        store = _store_above(clean, hit.start(), source, header)
        kind = _declared(source, header, hit['global'])
        if not store or not kind or hit['global'] in store.group(0):
            continue
        local = 'probe'
        if re.search(r'\b' + local + r'\b', clean[opening:end]):
            continue
        call = source[hit.start():hit.end()].replace('*' + hit['global'], '*' + local, 1)
        indent = hit['indent']
        text = (source[:store.start()] + f'{indent}{{\n{indent}{kind} *{local} = {hit["global"]};\n' +
                source[store.start():hit.start()] + call + f'{indent}}}\n' + source[hit.end():])
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILIES[1], text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
