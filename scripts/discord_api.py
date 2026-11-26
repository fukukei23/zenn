#!/usr/bin/env python3
"""discord_api.py — Discord REST API薄ラッパー（Bot Token認証・常駐プロセスなし）。

X自動化lib/discord_client.pyと同型設計（zenn側に独立配置・リポジトリ間importはしない）。
承認判定は「承認者ID照合方式」: approver_user_idがリアクションを付けたかのみ判定するため、
bot自身の初期リアクション（承認者と異なるID）は構造的に除外される。
"""
from __future__ import annotations

import urllib.parse

import requests

API_BASE = "https://discord.com/api/v10"
REACTION_APPROVE = "\U0001F44D"  # 👍
REACTION_REJECT = "\U0001F44E"  # 👎

EMOJI_NAMES = {
    "thumbsup": "approve", ":+1:": "approve", REACTION_APPROVE: "approve",
    "thumbsdown": "reject", ":-1:": "reject", REACTION_REJECT: "reject",
}


class DiscordAPIError(RuntimeError):
    """Discord API呼び出し失敗（401/403/429/5xx/通信エラー）。"""


def _headers(bot_token: str) -> dict:
    return {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}


def normalize_emoji(emoji: str) -> str:
    """絵文字表記をapprove/reject/その他に正規化する（unicode codepoint・Discord名両対応）。"""
    return EMOJI_NAMES.get(emoji, emoji)


def resolve_channel_id_from_webhook(webhook_url: str) -> str:
    """webhook URLからchannel_idを解決する（webhookオブジェクトにchannel_idフィールド実在）。"""
    try:
        resp = requests.get(webhook_url, timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"webhook取得中に通信エラー: {exc}") from exc
    if resp.status_code != 200:
        raise DiscordAPIError(f"webhook取得失敗: {resp.status_code}")
    channel_id = resp.json().get("channel_id")
    if not channel_id:
        raise DiscordAPIError("webhook応答にchannel_idが無い")
    return str(channel_id)


def send_message(channel_id: str, bot_token: str, content: str) -> str:
    """メッセージを送信しmessage_idを返す。401/403はDiscordAPIError（呼び出し側でDiscord通知）。"""
    try:
        resp = requests.post(
            f"{API_BASE}/channels/{channel_id}/messages",
            json={"content": content}, headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"メッセージ送信中に通信エラー: {exc}") from exc
    if resp.status_code in (401, 403, 429, 500, 502, 503):
        raise DiscordAPIError(f"メッセージ送信失敗: {resp.status_code} {resp.text[:200]}")
    if resp.status_code != 200:
        raise DiscordAPIError(f"メッセージ送信失敗: {resp.status_code} {resp.text[:200]}")
    return str(resp.json()["id"])


def add_reaction(channel_id: str, message_id: str, bot_token: str, emoji: str) -> None:
    """メッセージにリアクションを初期付与する（自分のメッセージにも付与可能）。"""
    encoded = urllib.parse.quote(emoji)
    try:
        resp = requests.put(
            f"{API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
            headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"リアクション付与中に通信エラー: {exc}") from exc
    if resp.status_code not in (200, 204):
        raise DiscordAPIError(f"リアクション付与失敗: {resp.status_code} {resp.text[:200]}")


def message_exists(channel_id: str, message_id: str, bot_token: str) -> bool:
    """メッセージが存在するか確認（404=削除済み→False・403等はDiscordAPIError）。"""
    try:
        resp = requests.get(
            f"{API_BASE}/channels/{channel_id}/messages/{message_id}",
            headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"メッセージ確認中に通信エラー: {exc}") from exc
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    raise DiscordAPIError(f"メッセージ確認失敗: {resp.status_code} {resp.text[:200]}")


def _get_reaction_user_ids(channel_id: str, message_id: str, bot_token: str,
                           normalized: str) -> set[str]:
    """指定emojiのリアクションを付けたuser_idの集合を取得する。

    normalized は "approve"/"reject" を想定（内部でcodepointへ戻す）。
    limit=100で1ページ取得（このチャンネルの反応者は少数想定・それでも
    after指定でページ送りは実装しない=超過時は全取得を諦めて空集合を返さず
    DiscordAPIErrorを投げる「取得失敗≠未承認」設計）。
    """
    emoji_code = {"approve": REACTION_APPROVE, "reject": REACTION_REJECT}[normalized]
    encoded = urllib.parse.quote(emoji_code)
    url = (f"{API_BASE}/channels/{channel_id}/messages/{message_id}"
           f"/reactions/{encoded}?limit=100")
    try:
        resp = requests.get(url, headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"リアクション取得中に通信エラー: {exc}") from exc
    if resp.status_code != 200:
        raise DiscordAPIError(f"リアクション取得失敗: {resp.status_code} {resp.text[:200]}")
    users = resp.json()
    if len(users) >= 100:
        # ページ上限に達した=取得漏れの可能性 → fail-closed
        raise DiscordAPIError("リアクション100件超=ページング未対応・取得を諦める（fail-closed）")
    return {str(u["id"]) for u in users}


def get_approval_decision(channel_id: str, message_id: str, bot_token: str,
                          approver_user_id: str) -> str:
    """承認判定を返す。"approve"/"reject"/"pending"/"error"。

    - 承認者ID照合方式: approver_user_idが付けたリアクションのみ判定対象
      （botの初期リアクション・他人のリアクションは構造的に除外される）
    - 👎優先（approverが両方付けた場合はreject=安全側）
    - API取得失敗は"error"（空集合≠未承認・fail-closed）
    """
    try:
        reject_users = _get_reaction_user_ids(channel_id, message_id, bot_token, "reject")
        if approver_user_id in reject_users:
            return "reject"
        approve_users = _get_reaction_user_ids(channel_id, message_id, bot_token, "approve")
        if approver_user_id in approve_users:
            return "approve"
        return "pending"
    except DiscordAPIError:
        return "error"


def send_error_notification(webhook_url: str, text: str) -> None:
    """checker失敗時のDiscordエラー通知（webhook経由・best effort・失敗しても例外を投げない）。"""
    try:
        requests.post(webhook_url, json={"content": f"⚠️ approve-checkエラー: {text}"},
                      timeout=15)
    except requests.exceptions.RequestException:
        pass
