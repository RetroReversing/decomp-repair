"""A statement run written out more than once, written once as a `static inline` helper that each place calls.

A controller-pak read and write routine of an N64 operating-system library (KMC GCC 2.7.2, 269 instructions) steps to
the next page of a file's chain in two loops: eleven lines that load the page table when the bank changes, take the next
entry and return an error code when it is out of range. Written out at both places the candidate was 14865 under
`-O2` and under `-O3`, with a larger frame and the helper's pointer accesses missing. The same lines as one
`static __inline__` function, called as `if ((ret = next_page(...)) != 0) return ret;`, were byte-identical at both
levels. The library's own source is likely to have had a static function there. Why it matters (integrate.c compiles the
body on its own and then expands it, so the locals passed by address are reached through pointers) is a hypothesis, not
confirmed in the compiler source.

`repeated_run_helper`
    Finds the longest runs of two or more statements that appear, in the same words, at two or more places of the
    function. Locals the run only reads are passed by value; locals it writes, takes the address of or reads members of
    are passed by pointer (`x.f` becomes `x->f`, `&x` becomes `x`); a scalar whose value no code after the run reads
    moves into the helper. A run with `return` keeps its meaning as a status helper: every returned value must be a
    nonzero literal or a variable the surrounding `if` found nonzero, the helper ends in `return 0;`, and each place
    returns the helper's result when it is not zero. Children: the function's parameters first and then the locals in
    each order (three or fewer; else declaration order and the order the run names them), and all in the order the run
    first names them.

A run with `goto`, a label, `case`, `break`, `continue`, a declaration or `static` is left alone. Whether a value is
read after the run is judged from the text, so the exact judge and a reading of the child decide.
"""
import re
from itertools import permutations

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close
from .switch_arm_helper import _parameters
from .switch_arm_return_helpers import _declared

FAMILY = 'repeated_run_helper'
FAMILIES = (FAMILY,)
RUNS = 3            # how many different runs are offered
ORDERED = 3         # up to this many locals, every order of them
MIN_TEXT = 60       # a shorter run (spaces apart) is a call and its argument, not a function
WRITE = r'\s*(?:=(?!=)|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<=|>>=|\+\+|--)'
SCALAR = re.compile(r'(?:(?:const|volatile|register|unsigned|signed)\s+)*'
                    r'(?:u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|char|short|int|long|float|double|unsigned|signed)'
                    r'(?:\s+(?:int|char|short|long))*\s*(?:\*[\s*]*)?$')


def _skip(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _statement(text, i, limit):
    """The end of the statement that starts at `i`, or None."""
    if i >= limit:
        return None
    if text[i] == '{':
        return close(text, i, '{', '}')
    word = re.compile(r'(if|for|while|switch|do)\b').match(text, i)
    if word and word[1] == 'do':
        body = _statement(text, _skip(text, word.end()), limit)
        tail = body and re.compile(r'\s*while\s*').match(text, body)
        after = tail and close(text, tail.end(), '(', ')')
        done = after and re.compile(r'\s*;').match(text, after)
        return done.end() if done else None
    if word:
        paren = _skip(text, word.end())
        if text[paren:paren + 1] != '(':
            return None
        after = close(text, paren, '(', ')')
        end = after and _statement(text, _skip(text, after), limit)
        if end and word[1] == 'if':
            other = re.compile(r'\s*else\b').match(text, end)
            if other:
                end = _statement(text, _skip(text, other.end()), limit)
        return end
    depth = 0
    for hit in re.compile(r'[(\[{)\]};]').finditer(text, i, limit):
        if hit[0] in '([{':
            depth += 1
        elif hit[0] in ')]}':
            depth -= 1
        elif not depth:
            return hit.end()
    return None


def _blocks(text, opening, end):
    """Every brace block of the body as its list of (start, stop) statements."""
    found = []
    for hit in re.finditer(r'{', text[opening:end]):
        brace = opening + hit.start()
        stop = close(text, brace, '{', '}')
        if not stop or re.search(r'[=,]\s*$', text[opening:brace]):
            continue
        rows, i = [], _skip(text, brace + 1)
        while i < stop - 1:
            after = _statement(text, i, stop - 1)
            if not after:
                break
            rows.append((i, after))
            i = _skip(text, after)
        found.append(rows)
    return found


def _runs(source, clean, blocks):
    """The repeated runs, longest first, each as the list of its places [(start, stop)]."""
    keys = [[re.sub(r'\s+', '', source[a:b]) for a, b in rows] for rows in blocks]
    seen = {}
    for n, rows in enumerate(blocks):
        for low in range(len(rows)):
            for high in range(low + 2, len(rows) + 1):
                key = tuple(keys[n][low:high])
                if sum(map(len, key)) >= MIN_TEXT:
                    seen.setdefault(key, []).append((rows[low][0], rows[high - 1][1]))
    ordered = sorted(seen.items(), key=lambda item: (-sum(map(len, item[0])), item[1]))
    chosen = []
    for _, places in ordered:
        apart = []
        for start, stop in sorted(places):
            if not apart or start >= apart[-1][1]:
                apart.append((start, stop))
        if len(apart) < 2 or any(all(any(a >= c and b <= d for c, d in other) for a, b in apart) for other in chosen):
            continue
        yield apart
        chosen.append(apart)


def _returns(text):
    """None when the run has no `return`; True when each returns a value that cannot be zero; else False."""
    hits = list(re.finditer(r'\breturn\b\s*(?P<value>[^;]*);', text))
    if not hits:
        return None
    for hit in hits:
        value = hit['value'].strip()
        literal = re.fullmatch(r'\(?\s*(-?\s*(?:0x[0-9A-Fa-f]+|\d+))\s*\)?', value)
        if literal and int(literal[1].replace(' ', ''), 0):
            continue
        if not re.fullmatch(IDENT, value):
            return False
        word = re.escape(value)
        guard = (r'\bif\s*\(\s*(?:' + word + r'|' + word + r'\s*!=\s*0|\(\s*' + word
                 + r'\s*=(?!=)[^{}]*\)\s*!=\s*0)\s*\)\s*{?\s*$')
        if not re.search(guard, text[:hit.start()]):
            return False
    return True


def _loop_bodies(clean, opening, end, at):
    for hit in re.finditer(r'\b(?:for|while|do)\b', clean[opening:end]):
        start = opening + hit.start()
        stop = _statement(clean, start, end)
        if stop and start < at < stop:
            yield start, stop


def _assigns(clean, hit, word):
    return bool(re.compile(r'\s*=(?!=)').match(clean, hit.end()))


def _dead_after(clean, opening, end, word, places):
    """Whether, as the text reads, nothing outside the places uses a value one of them left in `word`."""
    if re.search(r'(?<![&\w])&\s*' + word + r'\b', clean[opening:end]):
        return False
    mentions = [hit for hit in re.finditer(r'(?<![\w.>])' + word + r'\b', clean[opening:end])]
    outside = [(opening + h.start(), opening + h.end()) for h in mentions
               if not any(a <= opening + h.start() < b for a, b in places)]
    declared = re.compile(r'\b' + word + r'\s*;')
    for start, stop in places:
        first = re.search(r'(?<![\w.>])' + word + r'\b', clean[start:stop])
        if not first or not re.compile(r'\s*=(?!=)').match(clean, start + first.end()):
            return False
        later = [(a, b) for a, b in outside if a >= stop]
        for loop_start, loop_stop in _loop_bodies(clean, opening, end, start):
            later += [(a, b) for a, b in outside if loop_start <= a < start][:1]
        for a, b in later[:1] + later[len([1 for x, _ in later if x >= stop]):]:
            if not (re.compile(r'\s*=(?!=)').match(clean, b) or declared.match(clean, a)):
                return False
    return True


def _declaration(kind, word):
    return f'{kind}{"" if kind.endswith("*") else " "}{word}'


def _pointer(kind):
    return kind + ('*' if kind.endswith('*') else ' *')


def _variants(source, name, clean, span, part, places, parameters, locals_, kind):
    start, stop = places[0]
    text = clean[start:stop]
    if (re.search(r'\b(?:goto|case|default|static|break|continue)\b', text)
            or re.search(r'(?:^|[;{}])\s*' + IDENT + r'\s*:(?!:)', text) or _declared(text)):
        return []
    status = _returns(text)
    if status is False or (status and (not kind or kind == 'void' or '*' in kind)):
        return []
    used = []
    for hit in re.finditer(r'(?<![\w.])(?<!->)' + IDENT, text):
        word = hit[0]
        if word not in used and (word in parameters or word in locals_):
            used.append(word)
    moved, passed, pointers, arrays = [], [], set(), set()
    returned = set(re.findall(r'\breturn\s+(' + IDENT + r')\s*;', text))
    for word in used:
        entries = locals_.get(word)
        if entries and (len(entries) != 1 or not entries[0][3]):
            return []
        type_ = parameters.get(word) or entries[0][0]
        array = bool(entries and re.compile(r'[^;=\[(]*?\b' + word + r'\s*\[').match(clean, part.opening + entries[0][1]))
        written = re.search(r'(?<![\w.>])' + word + r'\b(?:\s*\[[^\]]*\]|\s*\.\s*' + IDENT + r')*' + WRITE, text)
        written = written or re.search(r'(?:\+\+|--)\s*' + word + r'\b', text)
        address = re.search(r'(?<![&\w\])])\s*(?<!&)&\s*' + word + r'\b', text)
        member = re.search(r'(?<![\w.>])' + word + r'\b\s*\.', text)
        if array:
            if address or re.search(r'\bsizeof\s*\(\s*' + word + r'\b', text):
                return []
            arrays.add(word)
        elif entries and SCALAR.match(type_) and not address and not member and _dead_after(clean, part.opening, part.end,
                                                                                           word, places):
            moved.append(word)
            continue
        elif written or address or member or (entries and not SCALAR.match(type_) and not type_.endswith('*')):
            pointers.add(word)
        passed.append(word)
    if returned - set(moved):
        return []
    types = {w: parameters.get(w) or locals_[w][0][0] for w in used}
    helper, n = f'{name}_step', 2
    while re.search(r'\b' + helper + r'\b', source):
        helper, n = f'{name}_step_{n}', n + 1
    body = source[start:stop]

    def inside(match):
        word = match['word']
        if word not in pointers:
            return match[0]
        if match['amp'] and not match['dot']:
            return word
        if match['dot']:
            return (match['amp'] or '') + word + '->'
        return f'(*{word})'

    if pointers:
        body = re.sub(r'(?P<amp>(?<![&\w\])])&\s*)?(?<![\w.])(?<!->)\b(?P<word>' + '|'.join(sorted(pointers))
                      + r')\b(?P<dot>\s*\.(?!\.))?', inside, body)
    lines = body.split('\n')
    indent = min((len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()), default=0)
    written_body = ['  ' + _declaration(types[w], w) + ';' for w in moved]
    written_body.append('  ' + lines[0].strip())
    written_body += ['  ' + line[indent:] if line.strip() else '' for line in lines[1:]]
    if status:
        written_body.append('  return 0;')

    # the caller's variable for a status result: the one the run returned itself, else a new one
    result = next(iter(returned)) if len(returned) == 1 else None
    declare = []
    if status and result is None:
        result = f'{name}_status'
        declare.append((part.opening + 1, part.opening + 1, f'\n    {kind} {result};'))
    # the function's own parameters first, in their order, then the locals in every order: where a local passed by
    # address gets its stack slot follows the order the arguments take the addresses in
    first = [w for w in parameters if w in passed]
    rest = sorted((w for w in passed if w not in parameters), key=lambda w: locals_[w][0][1])
    arrangements = permutations(rest) if len(rest) <= ORDERED else [rest, [w for w in passed if w in rest]]
    children = []
    for order in [first + list(arrangement) for arrangement in arrangements] + [passed]:
        signature = ', '.join(_declaration(_pointer(types[w]) if w in pointers or w in arrays else types[w], w)
                              for w in order) or 'void'
        arguments = ', '.join(('&' if w in pointers else '') + w for w in order)
        definition = (f'static inline {kind if status else "void"} {helper}({signature})\n{{\n'
                      + '\n'.join(written_body) + '\n}\n\n')
        call = f'{helper}({arguments})'
        edits = [(span[0], span[0], definition)] + declare
        for a, b in places:
            gap = source[source.rfind('\n', 0, a) + 1:a]
            pad = gap if not gap.strip() else ''
            new = (f'if (({result} = {call}) != 0) {{\n{pad}    return {result};\n{pad}}}' if status
                   else f'{call};')
            edits.append((a, b, new))
        # a declaration nothing names any more goes
        for word in moved:
            kept = clean[part.opening:part.end]
            for a, b in places:
                kept = kept[:a - part.opening] + ' ' * (b - a) + kept[b - part.opening:]
            if word != result and len(re.findall(r'\b' + word + r'\b', kept)) == 1:
                _, low, high, _ = locals_[word][0]
                low, high = part.opening + low, part.opening + high
                line = source.rfind('\n', 0, low) + 1
                finish = source.find('\n', high)
                if not source[line:low].strip() and not source[high:finish].strip():
                    low, high = line, finish + 1
                edits.append((low, high, ''))
        child = edit(source, edits)
        if child not in children:
            children.append(child)
    return children


def variants(source, name):
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    clean = part.clean
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', clean[span[0]:part.opening])
    if not head:
        return []
    kind = ' '.join(w for w in clean[span[0]:span[0] + head.start()].replace('*', ' * ').split()
                    if w not in ('static', 'inline', 'extern'))
    parameters = _parameters(clean, span[0], part.opening, name)
    locals_ = _declared(clean[part.opening:part.end])
    results, offered = [], 0
    for places in _runs(source, clean, _blocks(clean, part.opening, part.end)):
        made = _variants(source, name, clean, span, part, places, parameters, locals_, kind)
        results.extend((FAMILY, child) for child in made)
        offered += bool(made)
        if offered == RUNS:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # the registry: no caller wiring (registry.py)
