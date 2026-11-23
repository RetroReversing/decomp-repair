"""A global read again after stores through a pointer, read once into a local before the first store.

A load of a global that follows a store through a pointer is loaded again: the compiler cannot prove the pointer does
not point at the global, so `*p = a; *p += b; ... g ...; *p += c; ... g ...` reads `g` once per use after each store.
A developer who copied the global into a local first (`i = g;`) reads it once, and a local's load is also an insn of
its own for the scheduler, so it lands where the target loads it. The edit is one local, one load above the first
store of the run, and each read of the global in the run turned into the local (805 -> 295 in one 242-instruction
heightmap filter, KMC GCC 2.7.2; the saved best read the loop counter global four times after three stores through a
pointer to a pair of neighbouring globals).

A proposal takes a run of simple statements (consecutive lines of one block that open and close no brace) that holds a
store through a pointer (`*p = ...;`, `*p += ...;`, `p[k] = ...;`) and, after the first such store, two or more
statements that read the same `extern` integer global, with no call and no write to the global in the run. The local
(`held_G`) is declared at the top of the function and set just above the first store (or above the first read, when
one comes before it). One proposal for every read of the run and one for each shorter run ending at a later store (the reads after it stay
where they were: a read after the last store is the next iteration's). At most 8 proposals; the judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'global_read_local'
FAMILIES = (FAMILY,)
LIMIT = 8

_ID = r'[A-Za-z_]\w*'
_EXTERN = re.compile(rf'(?m)^[ \t]*extern\s+((?:(?:unsigned|signed|const|volatile)\s+)*(?:[su](?:8|16|32)|char|short|int|long))\s+({_ID})\s*;')
_STORE = re.compile(rf'^[ \t]*(?:\*\s*\(*\s*{_ID}|{_ID}\s*\[[^\]\n]*\])[^=\n;]*?(?<![=!<>])(?:[-+|&^*]|<<|>>)?=(?!=)')
_CALL = re.compile(rf'\b(?!(?:sizeof|if|while|for|switch|return)\b){_ID}\s*\(')


def _globals(text):
    return {name: kind for kind, name in _EXTERN.findall(text)}


def _lines(clean, opening, end):
    """(start, stop, depth at its start, text) of each line of the function body."""
    out, depth, at = [], 0, opening + 1
    for line in clean[opening + 1:end - 1].split('\n'):
        out.append((at, at + len(line), depth, line))
        depth += line.count('{') - line.count('}')
        at += len(line) + 1
    return out


def _simple(text):
    stripped = text.strip()
    return bool(stripped) and stripped.endswith(';') and '{' not in text and '}' not in text and not _CALL.search(text)


def _runs(lines):
    run = []
    for item in lines:
        if _simple(item[3]) and (not run or run[-1][2] == item[2]):
            run.append(item)
            continue
        if run:
            yield run
        run = [item] if _simple(item[3]) else []
    if run:
        yield run


def _reads(name, text):
    """The reads of `name` in a line: every use that is not the target of a plain or compound assignment, or `&name`."""
    assigned = re.match(rf'\s*{re.escape(name)}\s*(?:[-+|&^*/%]|<<|>>)?=(?!=)', text)
    taken = re.search(rf'&\s*{re.escape(name)}\b', text)
    uses = re.findall(rf'(?<![\w.]){re.escape(name)}\b', text)
    return 0 if assigned or taken else len(uses)


def variants(source, name, header=''):
    """Proposals: a global read after stores through a pointer, held in a local read before the first of them."""
    part = view(source, name)
    if not part:
        return []
    names = _globals(header + '\n' + part.clean[:part.opening])
    if not names:
        return []
    out = []
    used = set(re.findall(_ID, part.clean[part.opening:part.end]))
    for run in _runs(_lines(part.clean, part.opening, part.end)):
        stores = [index for index, item in enumerate(run) if _STORE.match(item[3])]
        if not stores:
            continue
        first = stores[0]
        for glob, kind in names.items():
            if glob not in used or f'held_{glob}' in used:
                continue
            if any(re.match(rf'\s*{re.escape(glob)}\s*(?:[-+|&^*/%]|<<|>>)?=(?!=)', item[3])
                   or re.search(rf'&\s*{re.escape(glob)}\b', item[3]) for item in run):
                continue
            reading = [index for index, item in enumerate(run) if _reads(glob, item[3])]
            after = [index for index in reading if index > first]
            if len(after) < 2 and not (reading and reading[0] <= first and len(reading) >= 2 and after):
                continue
            where = min(first, reading[0])
            local = f'held_{glob}'
            line = run[where]
            indent = re.match(r'[ \t]*', source[line[0]:line[1]]).group(0)
            # the reads after the last store through a pointer may stay (a later statement is its own loop-carried use)
            seen = set()
            for stop in (len(run), *[index for index in reversed(stores) if index > first]):
                chosen = tuple(index for index in reading if where <= index < stop)
                if chosen in seen or len([index for index in chosen if index > first]) < 2:
                    continue
                seen.add(chosen)
                edits = [(line[0], line[0], f'{indent}{local} = {glob};\n'),
                         (part.opening + 1, part.opening + 1, f'\n    {kind} {local};')]
                for index in chosen:
                    item = run[index]
                    text = source[item[0]:item[1]]
                    edits.append((item[0], item[1], re.sub(rf'(?<![\w.]){re.escape(glob)}\b', local, text)))
                out.append((FAMILY, edit(source, edits)))
                if len(out) >= LIMIT:
                    return list(dict.fromkeys(out))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 95}  # the registry: no caller wiring (registry.py)
