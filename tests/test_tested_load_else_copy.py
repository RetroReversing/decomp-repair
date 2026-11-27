"""A pointer loaded, tested and otherwise rebuilt: the load in a local of its own, copied in the `else` arm."""
import re

from decomprepair import registry
from decomprepair.tested_load_else_copy import FAMILY, variants

CODE = '''typedef struct Node {
    struct Node *prev;
    struct Node *head;
} Node;
extern void use(Node *a);

void f(Node *obj)
{
    Node *node;

    node = obj->head;
    if (node == NULL) {
        node = obj;
        while (node->prev != NULL) {
            node = node->prev;
        }
    }
    use(node);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_load_gets_a_local_of_its_own_and_the_else_arm_copies_it():
    [(family, text)] = variants(CODE, 'f')
    text = squash(text)
    assert family == FAMILY
    assert 'Node *node; Node *node_loaded;' in text
    assert 'node_loaded = obj->head; if (node_loaded == NULL) { node = obj;' in text
    assert 'node = node->prev; } } else { node = node_loaded; } use(node);' in text


def test_an_arm_that_reads_the_pointer_first_or_has_an_else_is_left_alone():
    assert not variants(CODE.replace('        node = obj;\n', '        use(node);\n        node = obj;\n'), 'f')
    assert not variants(CODE.replace('    }\n    use(node);', '    } else {\n        use(obj);\n    }\n    use(node);'), 'f')


def test_the_registry_runs_it():
    assert any(repair.module == 'tested_load_else_copy' for repair in registry.declared())
