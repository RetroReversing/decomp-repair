import copy

import pytest
from pycparser import c_ast, c_parser

from decomprepair.permuter_gen import protect_return_value


class Rejected(Exception):
    pass


def to_void(fn, ast, indices, region, random):
    # As decomp-permuter does it: a copied definition with a new return type replaces the old one.
    new = copy.copy(fn)
    new.decl = copy.copy(fn.decl)
    new.decl.type = copy.deepcopy(fn.decl.type)
    new.decl.type.type = c_ast.TypeDecl(declname=fn.decl.name, quals=[], align=[],
                                        type=c_ast.IdentifierType(['void']))
    ast.ext[ast.ext.index(fn)] = new


def parse(body):
    ast = c_parser.CParser().parse(f'int f(int a) {{ {body} }}')
    return ast, ast.ext[0]


def test_void_with_a_returned_value_is_rejected():
    ast, fn = parse('if (a) { return 1; } return 0;')
    with pytest.raises(Rejected):
        protect_return_value(to_void, Rejected)(fn, ast, None, None, None)


def test_void_without_a_returned_value_is_kept():
    ast, fn = parse('if (a) { return; } a = 1;')
    protect_return_value(to_void, Rejected)(fn, ast, None, None, None)


def test_an_unchanged_return_type_is_kept():
    ast, fn = parse('return a;')
    protect_return_value(lambda *args: None, Rejected)(fn, ast, None, None, None)
