import argparse
import asyncio

from core.actions import list_messages
from core.client_manager import ClientManager, safe_disconnect
from core.config import load_config, resolve_profile


async def main(profile: str, limit: int):
    config = load_config("config.yaml")
    profile_key, profile = resolve_profile(config, profile)
    manager = ClientManager(
        api_id=int(profile["api_id"]),
        api_hash=profile["api_hash"],
        phone_number=profile["phone_number"],
        proxy_url=profile.get("proxy"),
    )
    await manager.connect(profile_key)
    try:
        authorized = await manager.ensure_authorized(interactive=False)
        if not authorized:
            raise RuntimeError("Profile not authorized; run auth")
        messages = await list_messages(manager.client, "@VmomoVBot", limit, logger=_PrintLogger(), mark_read=False)
        for item in messages:
            print(f"[{item['date']}] {item['id']} {item['sender_id']}: {item['snippet']}")
    finally:
        await safe_disconnect(manager)


class _PrintLogger:
    def debug(self, *_args, **_kwargs):
        return None

    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None

    def exception(self, *_args, **_kwargs):
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="work_account")
    parser.add_argument("--limit", type=int, default=20)
    options = parser.parse_args()
    asyncio.run(main(options.profile, options.limit))
