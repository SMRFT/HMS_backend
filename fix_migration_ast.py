import ast

with open("hospital/migrations/0014_auto_20260603_1514.py", "r") as f:
    code = f.read()

tree = ast.parse(code)

for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "Migration":
        for body_node in node.body:
            if isinstance(body_node, ast.Assign) and body_node.targets[0].id == "operations":
                # Filter out DeleteModel and RemoveField
                new_ops = []
                for op in body_node.value.elts:
                    if isinstance(op, ast.Call) and isinstance(op.func, ast.Attribute):
                        if op.func.attr in ["DeleteModel", "RemoveField"]:
                            continue
                    new_ops.append(op)
                body_node.value.elts = new_ops

new_code = ast.unparse(tree)

with open("hospital/migrations/0014_auto_20260603_1514.py", "w") as f:
    f.write(new_code)
