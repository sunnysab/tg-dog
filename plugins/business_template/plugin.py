import typer

app = typer.Typer(help="Business plugin template")


@app.command()
def send(target: str, text: str):
    ctx = typer.get_current_context()
    context = ctx.obj or {}
    client = context["client"]
    logger = context["logger"]
    call = context.get("call")
    if call is None:
        raise RuntimeError("context.call is required for CLI mode")
    call(client.send_message(target, text))
    logger.info("Sent message to %s", target)


async def run(context, args):
    if len(args) < 2:
        raise ValueError("Usage: <target> <text>")
    target = args[0]
    text = " ".join(args[1:])
    await context["client"].send_message(target, text)
    context["logger"].info("Sent message to %s", target)
    return {"target": target}
