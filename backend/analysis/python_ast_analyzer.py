"""
Lightweight static analysis over student Python code via the `ast` module.

Intentionally narrow scope for v1: flag patterns that correlate with the
challenge bug categories in the spec (mutation-while-iterating,
off-by-one-shaped range() calls, etc.) as *hints* for bug_classifier.py --
not a general-purpose linter. Expand findings as new challenge categories
are added.
"""

import ast
from dataclasses import dataclass, field


@dataclass
class StaticFindings:
    parse_error: str | None = None
    mutates_list_while_iterating: bool = False
    uses_range_len_plus_offset: bool = False
    notes: list[str] = field(default_factory=list)


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.findings = StaticFindings()

    def visit_For(self, node: ast.For):
        # crude heuristic: `for x in some_list:` where the loop body calls
        # some_list.remove/append/pop -- classic "mutation while iterating".
        if isinstance(node.iter, ast.Name):
            iter_name = node.iter.id
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == iter_name
                    and child.func.attr in {"remove", "append", "pop", "insert"}
                ):
                    self.findings.mutates_list_while_iterating = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "range" and node.args:
            last_arg = node.args[-1]
            if isinstance(last_arg, ast.BinOp) and isinstance(last_arg.op, ast.Add):
                self.findings.uses_range_len_plus_offset = True
        self.generic_visit(node)


def analyze(code: str) -> StaticFindings:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return StaticFindings(parse_error=str(e))
    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.findings
