"""A call argument worked out of a global before the stores in front of the call, not after them.

    sMessages[gLine].text[gColumn + 1] = 0;          y = gLine * 15 + 0x3C;
    draw(sMessages[gLine].text, 0x5F,           ->    sMessages[gLine].text[gColumn + 1] = 0;
         gLine * 15 + 0x3C);                          draw(sMessages[gLine].text, 0x5F, y);

A store makes the compiler read a global again after it, so the argument written inside the call is computed from the
second load. A target that computes it from the first load (the shift it shares with the store's index sits before the
store) had it in a local assigned above the store. `temporary_hoist` only assigns a temporary right before its own
statement. Measured on a 42-instruction N64 message line drawer (SN GCC 2.8.1, `-G0 -mips3 -O2`): 1325 -> 0.

`call_argument_above_store`: an argument with arithmetic that reads an integer global, in a call that follows one or
more stores to other globals, is assigned to a new local above those stores (above all of them, and above the last).

`derived_local_reread`: a local that only copies a global, whose last use is inside an argument, holds the whole
argument instead, and its other uses read the global again (the same function: 175 -> 0).

A site is offered only when the stores in between name other globals as their destination and call nothing, so the
global keeps its value. A candidate only: the judge decides.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, view

HOIST = 'call_argument_above_store'
DERIVE = 'derived_local_reread'
FAMILIES = (HOIST, DERIVE)
LIMIT = 6

_TYPE = r'(?:(?:unsigned|signed)\s+(?:char|short|int|long)|[su](?:8|16|32)|char|short|int|long)'
_WORD = {'char', 'short', 'int', 'long', 'unsigned', 'signed', 's8', 'u8', 's16', 'u16', 's32', 'u32'}
_LINE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<text>[^;{}\n]+);[ \t]*$')
_CALL = re.compile(rf'(?:{IDENT}\s*=\s*)?(?P<callee>{IDENT})\s*\(')
_STORE = re.compile(rf'(?P<base>{IDENT})(?P<path>(?:\s*\[[^\[\]]*(?:\[[^\[\]]*\])?[^\[\]]*\]|\s*\.\s*{IDENT})*)'
                    r'\s*=(?!=)(?P<value>.*)')
_DECLARATION = re.compile(rf'(?!(?:return|goto|else)\b){IDENT}(?:\s+|\s*\*+\s*)+(?:{IDENT}(?:\s+|\s*\*+\s*))*{IDENT}'
                          r'\s*(?:\[[^\]]*\])?\s*(?:=(?!=).*)?')
_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'do'}


def _calls_something(text):
    return any(word not in _WORD for word in re.findall(rf'({IDENT})\s*\(', text))


def _pure(text):
    return not (_calls_something(text) or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', text))


def _globals(context):
    """(integer scalar globals, array globals) declared in `context`."""
    scalars = set(re.findall(rf'\bextern\s+{_TYPE}\s+({IDENT})\s*;', context))
    arrays = set(re.findall(rf'\bextern\s+[A-Za-z_][\w \t*]*?\b({IDENT})\s*\[[^;]*;', context))
    return scalars, arrays


def _store_target(text, scalars, arrays):
    """The global a plain store statement writes, when that cannot be any other global."""
    hit = _STORE.fullmatch(text.strip())
    if not hit or not _pure(hit['value']) or not _pure(hit['path']):
        return None
    base, path = hit['base'], hit['path'].strip()
    return base if (base in arrays and path.startswith('[')) or (base in scalars and not path) else None


def _arguments(clean, opening):
    """[(start, end)] of the arguments of the call whose `(` is at `opening`, and the index after its `)`."""
    spans, depth, start = [], 0, opening + 1
    for index in range(opening, len(clean)):
        char = clean[index]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
            if not depth:
                if clean[start:index].strip():
                    spans.append((start, index))
                return spans, index + 1
        elif char == ',' and depth == 1:
            spans.append((start, index))
            start = index + 1
    return [], 0


def _trim(clean, span):
    text = clean[span[0]:span[1]]
    return span[0] + len(text) - len(text.lstrip()), span[0] + len(text.rstrip())


def _call(clean, line):
    hit = _CALL.match(clean, line.start('text'))
    if not hit or hit['callee'] in _KEYWORDS or hit['callee'] in _WORD:
        return []
    spans, stop = _arguments(clean, hit.end() - 1)
    if not stop or clean[stop:line.end('text')].strip():
        return []
    return [_trim(clean, span) for span in spans]


def _arithmetic(text):
    """An argument worth a local: some operator joins a name with something else, and nothing is called or written."""
    return bool(_pure(text) and re.search(r'[\w\])]\s*(?:[*+|^&-]|<<|>>)\s*[\w(]', text)
                and not re.search(r'&\s*&|(?<![\w\])\s])\s*&|->|\[|\.[A-Za-z_]', text))


def _declarations_end(clean, opening, end):
    """Where the leading declarations of the body stop."""
    at = opening + 1
    for line in _LINE.finditer(clean, opening + 1, end):
        if clean[at:line.start()].strip() or not _DECLARATION.fullmatch(line['text'].strip()):
            break
        at = line.end() + 1
    return at


def _hoists(source, part, scalars, arrays):
    clean = part.clean
    lines = list(_LINE.finditer(clean, part.opening + 1, part.end))
    declared = set(re.findall(rf'(?m)^[ \t]*{_TYPE}\s+({IDENT})\b', clean[part.opening:part.end]))
    held = 'held'
    while re.search(rf'\b{held}\b', clean):
        held += '_'
    for number, line in enumerate(lines):
        arguments = _call(clean, line)
        if not arguments:
            continue
        stores, first = [], number
        while first and not clean[lines[first - 1].end():lines[first].start()].strip():
            before = lines[first - 1]
            target = _store_target(before['text'], scalars, arrays)
            if target is None or before['indent'] != line['indent']:
                break
            stores.append((before, target))
            first -= 1
        if not stores:
            continue
        for begin, stop in arguments:
            text = clean[begin:stop]
            names = set(re.findall(rf'(?<![\w.]){IDENT}', re.sub(rf'\b{NUMBER}\b', '', text)))
            read = names & scalars
            if not read or not _arithmetic(text) or names - scalars - declared - _WORD:
                continue
            # the longest run of stores first, then the last store alone
            for count in dict.fromkeys((len(stores), 1)):
                if any(target in names for _, target in stores[:count]):
                    continue
                at = stores[count - 1][0].start()
                top = _declarations_end(clean, part.opening, part.end)
                if top > at:
                    continue
                declare = f'{line["indent"]}s32 {held};\n'
                assign = f'{line["indent"]}{held} = {source[begin:stop]};\n'
                edits = [(top, top, declare + assign)] if top == at else [(top, top, declare), (at, at, assign)]
                yield HOIST, edit(source, edits + [(begin, stop, held)])


def _derived(source, part, scalars, arrays):
    clean = part.clean
    lines = list(_LINE.finditer(clean, part.opening + 1, part.end))
    copies = re.compile(rf'(?:(?P<type>{_TYPE})\s+)?(?P<local>{IDENT})\s*=\s*(?P<symbol>{IDENT})')
    for number, line in enumerate(lines):
        hit = copies.fullmatch(line['text'].strip())
        if not hit or hit['symbol'] not in scalars or hit['local'] in scalars:
            continue
        local, symbol = hit['local'], hit['symbol']
        word = re.compile(rf'(?<![\w.]){local}\b(?!\s*\()')
        body = clean[part.opening + 1:part.end]
        if not re.search(rf'\b{_TYPE}\s+{local}\b', body) or re.search(rf'&\s*{local}\b', body):
            continue
        uses = [part.opening + 1 + m.start() for m in word.finditer(body)]
        initial = line.start('text') + line['text'].index(local)
        if not uses or any(at < initial and not re.search(rf'{_TYPE}\s+$', clean[:at]) for at in uses):
            continue
        uses = [at for at in uses if at > initial]
        for later in lines[number + 1:]:
            arguments = _call(clean, later)
            if arguments:
                break
            text = later['text'].strip()
            target = _store_target(text, scalars, arrays)
            declaration = _DECLARATION.fullmatch(text) and _pure(text.partition('=')[2])
            if not declaration and (target is None or target == symbol or re.match(rf'{local}\b', text)):
                arguments = []
                break
        else:
            continue
        # nothing but those statements stands between the copy and the call, and the call is the local's last use
        if not arguments or clean[line.end():later.end()].count('{') + clean[line.end():later.end()].count('}') \
                or (uses and uses[-1] >= later.end()):
            continue
        for begin, stop in arguments:
            inside = [at for at in uses if begin <= at < stop]
            text = clean[begin:stop]
            if len(inside) != 1 or not _arithmetic(text) or any(at >= later.start() and at != inside[0]
                                                               and not any(a <= at < b for a, b in arguments)
                                                               for at in uses):
                continue
            offset = inside[0] - begin
            value = source[begin:stop][:offset] + symbol + source[begin:stop][offset + len(local):]
            start = line.start('text') + line['text'].index('=') + 1
            edits = [(start, line.end('text'), ' ' + value), (begin, stop, local)]
            edits += [(at, at + len(local), symbol) for at in uses if at != inside[0]]
            yield DERIVE, edit(source, edits)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    scalars, arrays = _globals(_blank(header) + '\n' + part.clean)
    result, seen = [], {source}
    for family, child in [*_derived(source, part, scalars, arrays), *_hoists(source, part, scalars, arrays)]:
        if child not in seen:
            seen.add(child)
            result.append((family, child))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
