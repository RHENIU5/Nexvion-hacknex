"""Safe arithmetic evaluator. Never uses eval(); only numbers and + - * / ** ( )."""
import ast
import operator as op

_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow}
_UN = {ast.USub: op.neg, ast.UAdd: op.pos}


def calculate(expression: str) -> float:
    if len(expression) > 200:
        raise ValueError("Expression too long")

    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            l, r = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(r) > 10: raise ValueError("Exponent too large")
            return _BIN[type(n.op)](l, r)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN: return _UN[type(n.op)](ev(n.operand))
        raise ValueError("Unsupported expression")

    return float(ev(ast.parse(expression.replace(",", ""), mode="eval")))
