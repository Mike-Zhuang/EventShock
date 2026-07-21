"""双语验证码邮件与 SMTP SSL 发送适配器。"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from backend.app.auth.models import AuthLocale, ChallengePurpose


class MailDeliveryError(RuntimeError):
    pass


class VerificationMailer(Protocol):
    async def sendVerificationCode(
        self,
        *,
        recipient: str,
        code: str,
        purpose: ChallengePurpose,
        locale: AuthLocale,
        expiresMinutes: int,
    ) -> None: ...


class SmtpVerificationMailer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        timeoutSeconds: float = 15.0,
    ) -> None:
        for name, value in (("host", host), ("username", username), ("sender", sender)):
            if not value or "\r" in value or "\n" in value:
                raise ValueError(f"invalid SMTP {name}")
        if not password:
            raise ValueError("SMTP password is required")
        if not 1 <= port <= 65_535:
            raise ValueError("SMTP port must be between 1 and 65535")
        if not 1.0 <= timeoutSeconds <= 60.0:
            raise ValueError("SMTP timeout must be between 1 and 60 seconds")
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self.sender = sender
        self.timeoutSeconds = timeoutSeconds

    def __repr__(self) -> str:
        return (
            f"SmtpVerificationMailer(host={self.host!r}, port={self.port}, credentials=<redacted>)"
        )

    async def sendVerificationCode(
        self,
        *,
        recipient: str,
        code: str,
        purpose: ChallengePurpose,
        locale: AuthLocale,
        expiresMinutes: int,
    ) -> None:
        message = _message(
            sender=self.sender,
            recipient=recipient,
            code=code,
            purpose=purpose,
            locale=locale,
            expiresMinutes=expiresMinutes,
        )
        try:
            await asyncio.to_thread(self._send, message)
        except (OSError, smtplib.SMTPException) as error:
            raise MailDeliveryError("verification email could not be delivered") from error

    def _send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            self.host,
            self.port,
            timeout=self.timeoutSeconds,
            context=context,
        ) as client:
            client.login(self.username, self._password)
            client.send_message(message)


def _message(
    *,
    sender: str,
    recipient: str,
    code: str,
    purpose: ChallengePurpose,
    locale: AuthLocale,
    expiresMinutes: int,
) -> EmailMessage:
    if "\r" in recipient or "\n" in recipient:
        raise ValueError("invalid recipient")
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError("verification code must contain six ASCII digits")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    if locale == "zh-CN":
        action = "注册账号" if purpose is ChallengePurpose.REGISTER else "重置密码"
        message["Subject"] = f"EventShock Lab {action}验证码"
        message.set_content(
            f"你正在使用 EventShock Lab {action}。\n\n"
            f"验证码：{code}\n\n"
            f"验证码将在 {expiresMinutes} 分钟后失效，且只能使用一次。"
            "\n如果不是你本人操作，请忽略此邮件。\n"
        )
    else:
        action = (
            "create your account" if purpose is ChallengePurpose.REGISTER else "reset your password"
        )
        message["Subject"] = "Your EventShock Lab verification code"
        message.set_content(
            f"You requested to {action} in EventShock Lab.\n\n"
            f"Verification code: {code}\n\n"
            f"This code expires in {expiresMinutes} minutes and can be used only once. "
            "If you did not request it, you can ignore this email.\n"
        )
    return message
