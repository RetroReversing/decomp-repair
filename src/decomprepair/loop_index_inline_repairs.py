"""Write a loop's index arithmetic where it is used, as the original source did, instead of through m2c's temporaries.

m2c names every intermediate and carries a masked loop index in a variable it sets before the loop and again at the
bottom of each pass:

    var_v1 = 0 & 0xFFFF;
    do {
        temp_a1 = var_v1 * 0x68;
        temp_v1 = temp_a1 + base;
        ... temp_a1 + base ... temp_a1 + base ...
        var_s0 += 1;
        var_v1 = var_s0 & 0xFFFF;
    } while (...);

The original wrote `(i & 0xFFFF) * 0x68 + base` at each use, which GCC 2.7.2 shares into one value in the register
the temporary only copied from. The named temporaries cost a copy and a register, and `single_use_inline` cannot
remove them because the carried variable is assigned again later in the function. Two rewrites, each only where its
conditions are proved from the text:

* a statement-level `temp = e;` in a `do` loop whose uses are all in that loop, before any operand of `e` changes
  in the pass, is written out at every use;
* a loop-carried copy `c = e;` set last in the pass (and before the loop to the same value) and read only before
  the operands of `e` change is replaced by `e` at its uses.

Both only propose; the compiler and the judge decide.
"""
import re

from .integer_repair_support import edit, view
from .local_inline_repairs import _changed, _plain

FAMILY = 'loop_index_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
_ASSIGN = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)[ \t]*=[ \t]*([^;{}=][^;{}]*);[ \t]*\n')
_NUMERIC = re.compile(r'[0-9xXa-fA-F\s()+\-*&|^<>~]+\Z')


def _python_close(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return -1


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(clean, opening):
        found = _scan.close_if(clean, opening, '{', '}', -1)
        return _python_close(clean, opening) if found is NotImplemented else found


def _loops(clean, base, end):
    """(do start, body start, body end, loop end) of each `do { ... } while (...);`, outermost first."""
    for match in re.finditer(r'\bdo\s*\{', clean[base:end]):
        opening = base + match.end() - 1
        closing = _close(clean, opening)
        tail = re.match(r'\}\s*while\s*\([^;]*\)\s*;', clean[closing:end]) if closing > 0 else None
        if tail:
            yield base + match.start(), opening + 1, closing, closing + tail.end()


def _depth_zero(clean, start, position):
    return clean[start:position].count('{') == clean[start:position].count('}')


def _names(expression):
    return set(re.findall(r'(?<![\w.])[A-Za-z_]\w*', expression))


def _declarations(clean, local):
    """How many plain `type local;` declarations the function has."""
    return len(re.findall(rf'(?m)^[ \t]*(?:volatile\s+)?[A-Za-z_][\w ]*?[ *]+{local}\s*;', clean))


def _spelled(expression):
    return expression if re.fullmatch(r'\w+', expression) else '(' + expression + ')'


def _inline_temporaries(source, name):
    part = view(source, name)
    if not part:
        return None
    clean, base = part.clean, part.opening + 1
    for do_start, start, stop, loop_end in _loops(clean, base, part.end):
        for match in _ASSIGN.finditer(clean[start:stop]):
            local, expression = match[2], source[start + match.start(3):start + match.end(3)].strip()
            position = start + match.start()
            if (not re.match(r'(?:temp|var)_', local) or not _plain(expression)
                    or not _depth_zero(clean, start, position) or local in _names(expression)):
                continue
            after = start + match.end()
            body = clean[after:stop]
            limit = len(body)
            for operand in _names(expression):
                found = re.search(rf'(?<![*\w]){operand}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\b{operand}\s*(?:\+\+|--)|(?:\+\+|--)\s*{operand}\b|&\s*{operand}\b', body)
                if found:
                    limit = min(limit, found.start())
            uses = [after + use.start() for use in re.finditer(rf'\b{local}\b', body)]
            others = [use.start() for use in re.finditer(rf'\b{local}\b', clean[base:part.end])]
            declared = _declarations(clean[base:part.end], local)
            if (not uses or any(use - after >= limit for use in uses) or _changed(local, body)
                    or len(others) != len(uses) + 1 + declared or re.search(rf'\b{local}\b', clean[stop:loop_end])):
                continue
            edits = [(position, start + match.end(), '')]
            edits += [(use, use + len(local), _spelled(expression)) for use in uses]
            return edit(source, edits)
    return None


def _value(expression, constants):
    text = expression
    for key, number in constants.items():
        text = re.sub(rf'\b{key}\b', str(number), text)
    if not _NUMERIC.match(text) or re.search(r'[A-Za-z_]', re.sub(r'0[xX][0-9a-fA-F]+', '', text)):
        return None
    try:
        return eval(text, {'__builtins__': {}}, {})  # digits and arithmetic only, checked above
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
        return None


def _substitute_carried(source, name):
    part = view(source, name)
    if not part:
        return None
    clean, base = part.clean, part.opening + 1
    for do_start, start, stop, loop_end in _loops(clean, base, part.end):
        last = list(_ASSIGN.finditer(clean[start:stop]))
        if not last or not clean[start + last[-1].end():stop].strip() == '':
            continue
        bottom = last[-1]
        carried, expression = bottom[2], source[start + bottom.start(3):start + bottom.end(3)].strip()
        if (not re.match(r'(?:temp|var)_', carried) or not _plain(expression) or carried in _names(expression)
                or not _depth_zero(clean, start, start + bottom.start())):
            continue
        before = re.search(rf'(?m)^[ \t]*{carried}[ \t]*=[ \t]*([^;{{}}=][^;{{}}]*);[ \t]*\n[ \t]*$', clean[base:do_start])
        if not before:
            continue
        initial = source[base + before.start(1):base + before.end(1)].strip()
        constants = {}
        for operand in _names(expression):
            sets = re.findall(rf'(?m)^[ \t]*{operand}[ \t]*=[ \t]*(0[xX][0-9a-fA-F]+|[0-9]+)[ \t]*;', clean[base:base + before.start()])
            writes = re.findall(rf'(?<![*\w]){operand}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', clean[base:do_start])
            if len(sets) != 1 or len(writes) != 1:
                break
            constants[operand] = int(sets[0], 0)
        else:
            if _value(initial, {}) is None or _value(initial, {}) != _value(expression, constants):
                continue
            body = clean[start:start + bottom.start()]
            limit = len(body)
            for operand in _names(expression):
                found = re.search(rf'(?<![*\w]){operand}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\b{operand}\s*(?:\+\+|--)|(?:\+\+|--)\s*{operand}\b|&\s*{operand}\b', body)
                if found:
                    limit = min(limit, found.start())
            uses = [start + use.start() for use in re.finditer(rf'\b{carried}\b', body)]
            outside = [m for m in re.finditer(rf'\b{carried}\b', clean[base:part.end])]
            declared = _declarations(clean[base:part.end], carried)
            if (not uses or any(use - start >= limit for use in uses) or _changed(carried, body)
                    or len(outside) != len(uses) + 2 + declared):
                continue
            edits = [(base + before.start(), base + before.end() - 0, '\n' if False else ''),
                     (start + bottom.start(), start + bottom.end(), '')]
            edits += [(use, use + len(carried), _spelled(expression)) for use in uses]
            return edit(source, edits)
    return None


def variants(source, name):
    result, seen = [], {source}

    def add(text):
        if text and text not in seen:
            seen.add(text)
            result.append((FAMILY, text))
    carried = _substitute_carried(source, name)
    for text in (carried, source):
        current = text
        while current:
            current = _inline_temporaries(current, name)  # every stage is a candidate: some temporaries stay in the original
            add(current)
    add(carried)
    return result[:LIMIT]
