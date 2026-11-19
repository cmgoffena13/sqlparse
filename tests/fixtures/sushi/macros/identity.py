from sqlmesh import macro


@macro()
def identity(evaluator, expr):
    return expr
