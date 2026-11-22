"""dominators and initialized were 394 and ~265 CPU seconds of a live Deep Permuter run; the faster versions must agree
with the straightforward ones on every graph."""
import random
import re
from types import SimpleNamespace

from decomprepair import local_flow
from decomprepair.allocator_call_guards import dominators
from decomprepair.pointer_pair_repairs import initialized


class Flow:
    memo, shape, remembered = local_flow.Flow.memo, local_flow.Flow.shape, local_flow.Flow.remembered
    reachability, _reachability = local_flow.Flow.reachability, local_flow.Flow._reachability

    def __init__(self, nodes, entry, clean=''):
        self.nodes, self.entry, self.part = nodes, entry, SimpleNamespace(clean=clean)


def _old_dominators(flow):
    if flow.entry is None:
        return {}
    reached, pending = set(), [flow.entry]
    while pending:
        index = pending.pop()
        if index not in reached:
            reached.add(index)
            pending.extend(flow.nodes[index].successors)
    parents = {index: set() for index in reached}
    for index in reached:
        for child in flow.nodes[index].successors & reached:
            parents[child].add(index)
    result = {index: ({index} if index == flow.entry else set(reached)) for index in reached}
    changed = True
    while changed:
        changed = False
        for index in reached - {flow.entry}:
            value = {index} | set.intersection(*(result[parent] for parent in parents[index]))
            if value != result[index]:
                result[index] = value
                changed = True
    return result


def _old_initialized(flow, variable):
    if flow.entry is None:return False
    reachable=set();pending=[flow.entry]
    while pending:
        index=pending.pop()
        if index in reachable:continue
        reachable.add(index);pending.extend(flow.nodes[index].successors)
    predecessors={i:set() for i in reachable}
    for i in reachable:
        for successor in flow.nodes[i].successors:predecessors[successor].add(i)
    outgoing={i:True for i in reachable};incoming={i:True for i in reachable}
    changed=True
    while changed:
        changed=False
        for i in sorted(reachable):
            node=flow.nodes[i]
            prior=i!=flow.entry and bool(predecessors[i]) and all(outgoing[p] for p in predecessors[i])
            text=flow.part.clean[node.start:node.end]
            assigned=bool(re.fullmatch(rf'\s*{re.escape(variable)}\s*=(?!=).*;\s*',text,re.S))
            after=assigned if variable in node.defines else prior
            if incoming[i]!=prior or outgoing[i]!=after:changed=True
            incoming[i],outgoing[i]=prior,after
    return all(variable not in flow.nodes[i].uses or incoming[i] for i in reachable)


def _random_flow(rng):
    count = rng.randint(1, 14)
    pieces, nodes = [], []
    for index in range(count):
        kind = rng.choice(['x = 1;', 'x = x + 1;', 'y = 2;', 'f(x);', 'x == 1;', 'g();'])
        start = sum(len(p) for p in pieces)
        pieces.append(kind)
        nodes.append(SimpleNamespace(
            start=start, end=start + len(kind), successors={rng.randrange(count) for _ in range(rng.randint(0, 3))},
            uses={'x'} if 'x' in kind.split('=')[-1] or kind.startswith('f(x') else set(),
            defines={'x'} if kind.startswith('x =') and not kind.startswith('x ==') else set()))
    entry = rng.choice([0, 0, 0, None]) if count else None
    return Flow(nodes, entry, ''.join(pieces))


def test_the_faster_passes_agree_with_the_plain_ones_on_random_graphs():
    rng = random.Random(7)
    for _ in range(600):
        flow = _random_flow(rng)
        assert dominators(flow) == _old_dominators(flow)
        assert initialized(flow, 'x') == _old_initialized(flow, 'x')
        assert initialized(flow, 'y') == _old_initialized(flow, 'y')


def test_a_flow_whose_edges_are_cut_in_place_is_analysed_afresh():
    """equal_value_flow and permuter_initialization rebind a node's successors; a stale answer would be wrong."""
    flow = Flow([SimpleNamespace(start=0, end=0, successors={1}, uses=set(), defines=set()),
                 SimpleNamespace(start=0, end=0, successors={2}, uses=set(), defines=set()),
                 SimpleNamespace(start=0, end=0, successors=set(), uses=set(), defines=set())], 0)
    assert dominators(flow)[2] == {0, 1, 2}
    flow.nodes[1].successors = set()
    assert dominators(flow) == {0: {0}, 1: {0, 1}}


def test_the_caller_may_change_its_answer_without_changing_the_next_one():
    flow = Flow([SimpleNamespace(start=0, end=0, successors={1}, uses=set(), defines=set()),
                 SimpleNamespace(start=0, end=0, successors=set(), uses=set(), defines=set())], 0)
    dominators(flow)[1].add(99)
    assert dominators(flow)[1] == {0, 1}


SOURCE = '''int sample(int input) {
    int value;
    int other;
    value = input;
    if (input) { other = value + 1; } else { other = 2; }
    while (other < 10) { other = other + value; }
    return other;
}'''


def _same(a, b):
    assert [(n.start, n.end, n.uses, n.defines, n.successors, n.live) for n in a.nodes] == \
           [(n.start, n.end, n.uses, n.defines, n.successors, n.live) for n in b.nodes]
    assert (a.entry, a.labels, a.gotos, a.names) == (b.entry, b.labels, b.gotos, b.names)
    assert [d['name'] for d in a.locals] == [d['name'] for d in b.locals]


def test_analyze_gives_each_caller_an_equal_flow_of_its_own():
    """About 40 families analyse one function in turn; the flow is built once but never shared, because they edit it."""
    local_flow._cache.clear()
    fresh = local_flow._analyze(SOURCE, 'sample', None, False)
    first = local_flow.analyze(SOURCE, 'sample')
    second = local_flow.analyze(SOURCE, 'sample')
    _same(first, fresh)
    _same(second, fresh)
    assert first is not second and first.nodes[0] is not second.nodes[0]
    first.nodes[1].successors.clear()
    first.nodes[1].uses.add('zzz')
    first.names.add('zzz')
    third = local_flow.analyze(SOURCE, 'sample')
    _same(third, fresh)


def test_analyze_remembers_a_refusal_and_distinguishes_declarations():
    local_flow._cache.clear()
    assert local_flow.analyze('int sample(int input) { int value = input;', 'sample') is None
    assert local_flow.analyze('int sample(int input) { int value = input;', 'sample') is None
    from decomprepair.integer_repair_support import locals_for, view
    declarations = locals_for(view(SOURCE, 'sample'))
    both = local_flow.analyze(SOURCE, 'sample', declarations=declarations)
    only_value = local_flow.analyze(SOURCE, 'sample', declarations=[d for d in declarations if d['name'] == 'value'])
    assert both.names == {'value', 'other'} and only_value.names == {'value'}


def test_graph_answers_are_shared_between_copies_but_follow_edge_cuts():
    local_flow._cache.clear()
    first, second = local_flow.analyze(SOURCE, 'sample'), local_flow.analyze(SOURCE, 'sample')
    assert dominators(first) == dominators(second)
    assert first.memo() is second.memo()
    assert second.reachability() is first.reachability()  # computed once for both
    for node in first.nodes:
        node.successors = set()  # a repair cutting every edge in place
    assert dominators(first) == {first.entry: {first.entry}}
    assert len(dominators(second)) > 1  # the other copy's graph is untouched
