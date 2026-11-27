"""shared_result_scratch: successive guarded call results go through one local, each kept under its own name."""
from decomprepair import registry
from decomprepair import shared_result_scratch as scratch

SOURCE = '''void f(Node *root) {
    Node *first;
    Node *second;
    Node *third;
    first = make();
    gCount = 1;
    if (first != NULL) {
        first->prev = root;
        root->next = first;
    }
    second = make();
    if (second != NULL) {
        second->prev = first;
        first->next = second;
    }
    third = make();
    if (third != NULL) {
        third->prev = second;
        second->next = third;
    }
}
'''

WANT = '''void f(Node *root) {
    Node *shared_result;
    Node *first;
    Node *second;
    shared_result = make();
    first = shared_result;
    gCount = 1;
    if (shared_result != NULL) {
        shared_result->prev = root;
        root->next = shared_result;
    }
    shared_result = make();
    second = shared_result;
    if (shared_result != NULL) {
        shared_result->prev = first;
        first->next = shared_result;
    }
    shared_result = make();
    if (shared_result != NULL) {
        shared_result->prev = second;
        second->next = shared_result;
    }
}
'''


def test_one_scratch_receives_every_result():
    assert scratch.variants(SOURCE, 'f') == [(scratch.FAMILY, WANT)]


def test_a_single_site_or_a_result_written_again_is_left_alone():
    one = 'void f(void) {\n    Node *a;\n    a = make();\n    if (a != NULL) {\n        a->x = 1;\n    }\n}\n'
    assert scratch.variants(one, 'f') == []
    rewritten = SOURCE.replace('root->next = first;', 'first = NULL;').replace(
        '    third = make();\n    if (third', '    second = 0;\n    third = make();\n    if (third')
    assert scratch.variants(rewritten, 'f') == []


def test_it_declares_itself_to_the_registry():
    repair = registry.get('shared_result_scratch')
    assert repair is not None and registry.problems(repair) == []
