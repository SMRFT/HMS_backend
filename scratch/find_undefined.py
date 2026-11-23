import ast

with open(r"D:\HMS (1)\HMS_backend\hospital\Views\cashcounter.py", "r", encoding="utf-8") as f:
    content = f.read()

tree = ast.parse(content)

# Find all global names, imports, etc.
import builtins
builtin_names = set(dir(builtins))

class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.defs = set()
        self.uses = []

scopes = [Scope()]

class Visitor(ast.NodeVisitor):
    def visit_FunctionDef(self, node):
        scopes[-1].defs.add(node.name)
        scopes.append(Scope(scopes[-1]))
        # add args
        for arg in node.args.args:
            scopes[-1].defs.add(arg.arg)
        if node.args.vararg:
            scopes[-1].defs.add(node.args.vararg.arg)
        if node.args.kwarg:
            scopes[-1].defs.add(node.args.kwarg.arg)
        self.generic_visit(node)
        s = scopes.pop()
        # check undefined in s
        for name, lineno in s.uses:
            if not self.is_defined(s, name):
                print(f"Undefined variable '{name}' at line {lineno}")

    def is_defined(self, scope, name):
        if name in builtin_names:
            return True
        curr = scope
        while curr:
            if name in curr.defs:
                return True
            curr = curr.parent
        return False

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            scopes[-1].defs.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            scopes[-1].uses.append((node.id, node.lineno))
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            scopes[-1].defs.add(alias.asname or alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            scopes[-1].defs.add(alias.asname or alias.name)
        self.generic_visit(node)

v = Visitor()
v.visit(tree)
