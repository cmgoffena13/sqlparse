from sqlmesh import model


@model(
    "sushi.waiters",
    kind="FULL",
    columns={
        "waiter_id": "int",
    },
)
def entrypoint(context, **kwargs):
    return "SELECT 1 AS waiter_id"
