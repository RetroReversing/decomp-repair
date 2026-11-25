"""phase_lifetime_repairs.reaching, as a worklist, finds the same reaching definitions as sweeping until nothing changes."""
import random
from types import SimpleNamespace

from decomprepair.phase_lifetime_repairs import reaching


def _sweeping(flow, variable, reachable):
    parents = {i: set() for i in reachable}
    for i in reachable:
        for child in flow.nodes[i].successors & reachable:
            parents[child].add(i)
    incoming, outgoing = {i: set() for i in reachable}, {i: set() for i in reachable}
    changed = True
    while changed:
        changed = False
        for i in reachable:
            value = set().union(*(outgoing[p] for p in parents[i]))
            if i == flow.entry:
                value.add(-1)
            after = {i} if variable in flow.nodes[i].defines else value
            if value != incoming[i] or after != outgoing[i]:
                incoming[i], outgoing[i] = value, after
                changed = True
    return incoming


def test_the_worklist_matches_the_sweep_on_random_graphs():
    rng = random.Random(5)
    for _ in range(400):
        n = rng.randint(1, 14)
        nodes = [SimpleNamespace(successors={rng.randrange(n) for _ in range(rng.randint(0, 3))},
                                 defines={"v"} if rng.random() < 0.3 else set()) for _ in range(n)]
        flow = SimpleNamespace(nodes=nodes, entry=0)
        reachable = {i for i in range(n) if rng.random() < 0.85} | {0}
        assert reaching(flow, "v", reachable) == _sweeping(flow, "v", reachable)
