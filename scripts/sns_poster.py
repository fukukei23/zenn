#!/usr/bin/env python3
"""Post article announcement to SNS via BulkPublish API."""

import json
import os
import sys

try:
    from bulkpublish import BulkPublish
except ImportError:
    BulkPublish = None


def main():
    slug = os.environ.get("ARTICLE_SLUG", "")
    title = os.environ.get("ARTICLE_TITLE", "")
    api_key = os.environ.get("BULK_PUBLISH_API_KEY", "")

    if not slug or not title:
        print("ARTICLE_SLUG or ARTICLE_TITLE not set")
        sys.exit(0)

    if not api_key:
        print("BULK_PUBLISH_API_KEY not set, skipping SNS post")
        sys.exit(0)

    if BulkPublish is None:
        print("bulkpublish package not installed, skipping")
        sys.exit(0)

    article_url = f"https://zenn.dev/fukukei23/articles/{slug}"

    content = f"""新着記事: {title}

{article_url}

#AI #LLM #Claude #エンジニア転職 #Python"""

    try:
        bp = BulkPublish(api_key)
        channels = bp.channels.list()

        if not channels:
            print("No connected channels found in BulkPublish")
            sys.exit(0)

        # X (Twitter) requires BulkPublish Pro plan — skip it, use tweetly instead
        skip_platforms = {"x", "twitter"}
        channel_list = []
        for ch in channels:
            platform = ch.get("platform", "").lower()
            if platform in skip_platforms:
                print(f"Skipping {platform} (use tweetly for X)")
                continue
            channel_list.append({
                "channelId": ch.get("id") or ch.get("channelId"),
                "platform": ch.get("platform"),
            })

        if not channel_list:
            print("No channels after filtering (only X was connected)")
            sys.exit(0)

        print(f"Posting to {len(channel_list)} channels: {[c['platform'] for c in channel_list]}")

        post = bp.posts.create(
            content=content,
            channels=channel_list,
            status="published",
        )

        print(f"SNS post created: {post}")

    except Exception as e:
        print(f"SNS post failed (article already published): {e}")
        sys.exit(0)


if __name__ == "__main__":
    main()
