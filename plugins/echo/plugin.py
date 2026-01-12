async def run(context, args):
    logger = context["logger"]
    logger.info("echo plugin args: %s", args)
    return {"args": args}
