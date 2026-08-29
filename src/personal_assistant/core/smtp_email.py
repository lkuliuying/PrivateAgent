"""注册验证码 SMTP 投递与 HTML 邮件模板。"""
from __future__ import annotations

import html
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from ..config import settings


class SmtpConfigurationError(RuntimeError):
    """SMTP 配置缺失或包含不安全的邮件头值。"""


class EmailDeliveryError(RuntimeError):
    """SMTP 服务连接、认证或投递失败。"""


def _safe_header(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        raise SmtpConfigurationError(f"{label} 未配置或格式无效")
    return normalized


def _validate_smtp_host(host: str) -> None:
    """拒绝不可用的示例值和带 URL 协议/路径的 SMTP 主机。"""
    normalized = host.strip()
    if normalized.casefold() == "smtp.example.com":
        raise SmtpConfigurationError(
            "SMTP 主机仍是示例地址，请在 smtp.env 的 PA_SMTP_HOST 中填写邮箱服务商的真实 SMTP 域名"
        )
    if "://" in normalized or "/" in normalized or any(
        character.isspace() for character in normalized
    ):
        raise SmtpConfigurationError(
            "SMTP 主机格式无效：PA_SMTP_HOST 只填写域名或 IP，不要包含 http://、https:// 或路径"
        )


def _delivery_error_message(exc: BaseException) -> str:
    """把常见 SMTP 故障转换为不泄露凭据的可操作提示。"""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP 认证失败，请检查登录邮箱和 SMTP 授权码"
    if isinstance(exc, socket.gaierror):
        return "SMTP 主机无法解析，请检查 smtp.env 中的 PA_SMTP_HOST 是否为真实 SMTP 域名"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "连接 SMTP 服务超时，请检查 SMTP 主机、端口和网络"
    if isinstance(exc, ConnectionRefusedError):
        return "SMTP 服务拒绝连接，请检查端口以及 SSL/STARTTLS 配置"
    if isinstance(exc, ssl.SSLError):
        return "SMTP SSL/TLS 握手失败，请检查端口以及 SSL/STARTTLS 配置"
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "SMTP 服务拒绝发件地址，请确认发件邮箱与登录邮箱一致"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "SMTP 服务拒绝收件地址，请检查接收验证码的邮箱"
    if isinstance(exc, smtplib.SMTPConnectError):
        return "SMTP 服务连接失败，请检查主机、端口以及 SSL/STARTTLS 配置"
    return "验证码邮件发送失败，请检查 SMTP 配置和邮箱服务商状态"


def build_verification_email(
    recipient: str,
    code: str,
    *,
    valid_minutes: int,
) -> EmailMessage:
    """构建同时包含纯文本与内联样式 HTML 的验证码邮件。"""
    sender_email = _safe_header(
        settings.smtp_from_email or settings.smtp_username,
        label="SMTP 发件邮箱",
    )
    sender_name = _safe_header(settings.smtp_from_name, label="SMTP 发件名称")
    recipient = _safe_header(recipient, label="收件邮箱")
    safe_code = html.escape(code)

    message = EmailMessage()
    message["Subject"] = "PrivateAgent 邮箱验证码"
    message["From"] = formataddr((sender_name, sender_email))
    message["To"] = recipient
    message.set_content(
        f"你的 PrivateAgent 注册验证码是：{code}\n"
        f"验证码将在 {valid_minutes} 分钟后失效，请勿转发给他人。"
    )
    message.add_alternative(
        f"""<!doctype html>
<html lang="zh-CN">
  <body style="margin:0;padding:0;background:#f3f6fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;color:#172033;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f6fb;padding:36px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #e3e9f2;border-radius:20px;overflow:hidden;box-shadow:0 18px 48px rgba(27,48,82,.10);">
            <tr>
              <td style="padding:28px 34px;background:linear-gradient(135deg,#0b1f42,#174c83);color:#ffffff;">
                <div style="font-size:13px;letter-spacing:.16em;color:#8edaff;font-weight:700;">PRIVATEAGENT</div>
                <div style="margin-top:8px;font-size:25px;font-weight:700;">验证你的邮箱</div>
              </td>
            </tr>
            <tr>
              <td style="padding:34px;">
                <p style="margin:0 0 18px;font-size:15px;line-height:1.8;color:#526078;">你正在创建 PrivateAgent 账号，请在注册页面输入以下验证码：</p>
                <div style="padding:20px;text-align:center;border:1px solid #dce6f3;border-radius:14px;background:#f7faff;color:#1264d7;font-size:34px;font-weight:800;letter-spacing:.28em;">{safe_code}</div>
                <p style="margin:20px 0 0;font-size:13px;line-height:1.8;color:#7a879b;">验证码有效期为 <strong>{valid_minutes} 分钟</strong>。若这不是你的操作，请忽略本邮件，不要向任何人透露验证码。</p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 34px;border-top:1px solid #edf1f6;background:#fafbfd;font-size:12px;color:#98a2b3;">此邮件由 PrivateAgent 自动发送，请勿直接回复。</td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>""",
        subtype="html",
    )
    return message


def send_registration_verification_email(
    recipient: str,
    code: str,
    *,
    valid_minutes: int,
) -> None:
    """同步投递邮件；API 层通过线程运行，避免阻塞事件循环。"""
    host = settings.smtp_host.strip()
    username = settings.smtp_username.strip()
    password = (
        settings.smtp_password.get_secret_value()
        if settings.smtp_password is not None
        else ""
    )
    if not host or not username or not password:
        raise SmtpConfigurationError("SMTP 服务尚未完整配置")
    _validate_smtp_host(host)

    message = build_verification_email(
        recipient,
        code,
        valid_minutes=valid_minutes,
    )
    try:
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
                context=ssl.create_default_context(),
            ) as client:
                client.login(username, password)
                client.send_message(message)
            return

        with smtplib.SMTP(
            host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as client:
            client.ehlo()
            if settings.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(username, password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError(_delivery_error_message(exc)) from exc
