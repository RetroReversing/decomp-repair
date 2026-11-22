"""A `volatile` the draft's own search left on a local, dropped.

A `volatile` local forces a load and a store at each access, a stack slot of its own and a scheduling barrier: a
search that found a lower score with one keeps it, and every later step works around it. In a 719-instruction N64
function it hid three effects at once (the spill that gave the frame its extra 8 bytes, the branches of a compound
test, the register order of two loads). Without it the same source scores worse until the frame is declared as a
plain unused local (`unused_frame_padding`) and the test compares the stored memory (`stored_value_compare`), and
then is 4405 against 5910. Each `volatile` local declaration gets one variant with the qualifier removed. A candidate
rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, declaration_end, lines

FAMILY = 'volatile_local_drop'
FAMILIES = (FAMILY,)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    end = declaration_end(part)
    if end is None:
        return []
    out = []
    for line in lines(part, source):
        if line.start >= end:
            break
        hit = re.match(r'(?P<pre>[ \t]*)volatile[ \t]+', line.text)
        if hit:
            out.append((FAMILY, apply(source, [(line.start + len(hit['pre']), line.start + hit.end(), '')])))
    return out
