"""A switch arm's dead exits, taken out: `if (x || y) { break; } else { break; }` and `do { break; } while (0);`.

m2c emits the test of a branch whose two sides were the same jump (`if (var_s2 || temp_a3) { break; } else { break; }`)
and, where a `goto` target sat at the end of an arm, `do { break; } while (0);`. Neither makes code, but both count:
every name in the dead test is a use that the register allocator's priorities see (the masks of a state machine in a
417-instruction input handler had 20 references for 8 real ones, and the loop's continue flag, with 14, ranked below
them, the opposite of the target's order: three `andi` registers shifted by one), and the `do { break; } while (0);`
that sits between two `case` labels is a `break` of its own loop, not of the switch, so the arm above it also runs the
one below. Taking them out leaves the arm's real exit and the references the game's code had.

Offered once for the function (all of them in one child): an `if (...) { break; } else { break; }` becomes `break;`
(it exits the switch the same way), and a `do { break; } while (0);` is removed, or becomes the `break;` it was meant to
be when the next `case` or `default` follows it at once (the arm above it then no longer falls into the next one: the
saved source of a 417-instruction input handler ran its fifth arm into its sixth, and the target's arm ends in a jump).
A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'switch_dead_exit_strip'
FAMILIES = (FAMILY,)
_IF = re.compile(r'\bif\s*\(')
_DO = re.compile(r'\bdo\s*\{\s*break\s*;\s*\}\s*while\s*\(\s*0\s*\)\s*;')
_BREAK_ARM = re.compile(r'\s*\{\s*break\s*;\s*\}')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    edits = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        then = _BREAK_ARM.match(clean, shut) if shut else None
        other = re.compile(r'\s*else\b').match(clean, then.end()) if then else None
        otherwise = _BREAK_ARM.match(clean, other.end()) if other else None
        if otherwise and not re.search(r'\w\s*\(', clean[hit.end():shut - 1]):  # a test that calls something stays
            edits.append((hit.start(), otherwise.end(), 'break;'))
    for hit in _DO.finditer(clean, part.opening + 1, part.end):
        # right before the next label the author meant to leave the switch: the real `break;`
        edits.append((hit.start(), hit.end(), 'break;' if re.match(r'\s*(?:case\b|default\s*:)', clean[hit.end():]) else ''))
    return [(FAMILY, edit(source, edits))] if edits else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
