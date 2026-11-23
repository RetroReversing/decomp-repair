"""A `do { } while (0)` wrapper taken off one statement and an empty one put after a later statement: the boundary moves down.

    do { a[i] = y; } while (0);                 a[i] = y;
    b[0][i] = q;                       ->       b[0][i] = q;
    if (n > 0) { for (...) { ... } }            do { } while (0);
                                                if (n > 0) { for (...) { ... } }

A `do { } while (0)` is a pair of loop notes (NOTE_INSN_LOOP_BEG/END): they end a scheduling block, and a loop-pass movable
set inside one is hoisted only as far as its own preheader. A wrapper around a statement puts the boundary before and after
that statement; an empty one puts a boundary at a single point. On a KMC GCC 2.7.2 menu builder (`-G0 -mips3 -mgp32 -mfp32 -O2`,
535 instructions) the wrapper on a halfword store and the statement after it were both exact before the loop test, but the
store of the next statement was scheduled after the load of the loop bound and moved into the branch's delay slot; the
target keeps the store above the load (the first scheduler places two independent memory references by priority, and a loop
note between them fixes their order). Taking the wrapper off the earlier statement and putting an empty one after the next
went 330 -> 260 together: each alone is no better (the wrapper alone off: 955; the fence alone: 330). One child per statement
that has a wrapper layer, shifting past one or two following simple statements (`wrapper_boundary_shift`); the candidate is
never a verdict: the judge decides. The same function needed the redundant entry guard `if (n > 0) { for (k = 0; k < n; k++) {...} }`
written as the bare `for` for the fence to land where the target has it (the guard alone changes nothing: 330 -> 330), so
every child is offered once more with it dropped (`wrapper_boundary_shift_guard`; 330 -> 260). Evidence level: one function.
"""
import re

from . import csource
from .c_scan import close

FAMILY = 'wrapper_boundary_shift'
FAMILY_GUARD = 'wrapper_boundary_shift_guard'
FAMILIES = (FAMILY, FAMILY_GUARD)
_WRAPPED = re.compile(r'^(?P<ind>[ \t]*)(?P<open>(?:do \{ )+)(?P<stmt>[^{}\n]*?;)(?P<close>(?: \} while \(0\);)+)[ \t]*$')
_GUARD = re.compile(r'(?P<ind>[ \t]*)if \((?P<n>[A-Za-z_]\w*) > 0\) \{\s*for \((?P<v>[A-Za-z_]\w*) = 0; (?P=v) < (?P=n);')
_SIMPLE = re.compile(r'^[ \t]*(?!(?:if|for|while|do|switch|case|default|else|return|goto|break|continue|typedef)\b)[^#{}\n]*;[ \t]*$')


def _unwrap(line):
    m = _WRAPPED.match(line)
    if not m or m['open'].count('do { ') != m['close'].count(' } while (0);'):
        return None
    layers = m['open'].count('do { ')
    inner = m['stmt'] if layers == 1 else ('do { ' * (layers - 1)) + m['stmt'] + (' } while (0);' * (layers - 1))
    return m['ind'] + inner, m['ind']


def _drop_guard(source, name):
    """The source with the first `if (n > 0) { for (v = 0; v < n; ...) {...} }` written as the bare `for`, or None.

    The guard repeats the loop's own first test, so the compiler's loop entry test is the one the target has either way; with
    the guard the scheduler sees one more block boundary before the loop."""
    span = csource.find(source, name)
    clean = csource._blank(source)
    for m in _GUARD.finditer(clean, *span) if span else ():
        open_if = clean.index('{', m.start())
        shut_if = close(clean, open_if)
        for_at = clean.index('for', open_if)
        open_for = clean.index('{', clean.index(')', for_at))
        shut_for = close(clean, open_for)
        if shut_if > 0 and shut_for > 0 and clean[shut_for + 1:shut_if].strip() == '':
            return source[:m.start()] + m['ind'] + source[for_at:shut_for + 1] + source[shut_if + 1:]
    return None


def variants(source, name):
    span = csource.find(source, name)
    if not span:
        return []
    lines = source.split('\n')
    start = source.count('\n', 0, span[0])
    end = source.count('\n', 0, span[1])
    out = []
    for i in range(start, min(end + 1, len(lines))):
        un = _unwrap(lines[i])
        if not un:
            continue
        text, indent = un
        for distance in (1, 2):
            at = i + distance
            if at >= len(lines) or not all(_SIMPLE.match(lines[k]) and not _WRAPPED.match(lines[k]) for k in range(i + 1, at + 1)):
                break
            child = lines[:i] + [text] + lines[i + 1:at + 1] + [indent + 'do { } while (0);'] + lines[at + 1:]
            out.append((FAMILY, '\n'.join(child)))
            bare = _drop_guard('\n'.join(child), name)
            if bare:
                out.append((FAMILY_GUARD, bare))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
