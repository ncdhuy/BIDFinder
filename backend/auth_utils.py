import asyncio
import hashlib
import os
import re
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import asyncpg
from fastapi import HTTPException, Request, Response

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import id_token as google_id_token
    GOOGLE_AUTH_IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - depends on environment packages
    GoogleAuthRequest = None
    google_id_token = None
    GOOGLE_AUTH_IMPORT_ERROR = str(exc)

POSITION_OPTION_GROUPS = [
    {
        "label": "Doanh nghiệp",
        "options": [
            "Công ty dược",
            "Đơn vị tư vấn đấu thầu",
        ],
    },
    {
        "label": "Cơ sở khám chữa bệnh",
        "options": [
            "Khoa Dược",
            "Phòng Kế hoạch tổng hợp",
            "Phòng Vật tư thiết bị y tế",
            "Các phòng chức năng khác",
            "Khối lâm sàng",
            "Khối cận lâm sàng",
        ],
    },
    {
        "label": "Đào tạo và nghiên cứu",
        "options": [
            "Giảng viên/Nghiên cứu viên",
            "Sinh viên/Học viên",
        ],
    },
    {
        "label": "Cơ quan/tổ chức khác",
        "options": [
            "Cơ quan quản lý/bảo hiểm/sở ngành",
            "Khác",
        ],
    },
]
POSITION_OPTIONS = [
    option
    for group in POSITION_OPTION_GROUPS
    for option in group["options"]
]

PASSWORD_MIN_LENGTH = max(9, int(os.getenv("AUTH_PASSWORD_MIN_LENGTH", "9")))
SESSION_TTL_DAYS = max(1, int(os.getenv("AUTH_SESSION_TTL_DAYS", "30")))
PBKDF2_ITERATIONS = max(120_000, int(os.getenv("AUTH_PBKDF2_ITERATIONS", "240000")))
PASSWORD_RESET_TTL_MINUTES = max(5, int(os.getenv("AUTH_PASSWORD_RESET_TTL_MINUTES", "30")))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_POLICY_MESSAGE = "Mật khẩu phải có ít nhất 9 ký tự, bao gồm ít nhất 1 chữ số và 1 chữ cái in hoa."
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {"1", "true", "yes", "on"}
AUTH_SESSION_COOKIE_NAME = os.getenv("AUTH_SESSION_COOKIE_NAME", "bidfinder_session")
AUTH_COOKIE_DOMAIN = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
AUTH_COOKIE_SECURE_MODE = os.getenv("AUTH_COOKIE_SECURE_MODE", "auto").strip().lower()
AUTH_COOKIE_SAMESITE_MODE = os.getenv("AUTH_COOKIE_SAMESITE_MODE", "auto").strip().lower()
SMTP_HOST = os.getenv("AUTH_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("AUTH_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("AUTH_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("AUTH_SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("AUTH_SMTP_FROM_EMAIL", SMTP_USERNAME).strip()
SMTP_FROM_NAME = os.getenv("AUTH_SMTP_FROM_NAME", "BIDFinder").strip() or "BIDFinder"
SMTP_USE_TLS = os.getenv("AUTH_SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
SMTP_USE_SSL = os.getenv("AUTH_SMTP_USE_SSL", "false").strip().lower() in {"1", "true", "yes", "on"}
PASSWORD_RESET_BASE_URL = os.getenv("AUTH_PASSWORD_RESET_URL_BASE", "").strip()
FRONTEND_BASE_URL = os.getenv("APP_FRONTEND_URL", "").strip()


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_email(email: Any) -> str:
    return normalize_text(email).lower()


def is_local_request(request: Request) -> bool:
    host = (getattr(request.url, "hostname", "") or "").lower()
    return host in {"localhost", "127.0.0.1"}


def get_request_scheme(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded_proto = request.headers.get("x-forwarded-proto", "").strip().lower()
        if forwarded_proto:
            return forwarded_proto.split(",")[0].strip()
    return request.url.scheme


def resolve_cookie_secure(request: Request) -> bool:
    if AUTH_COOKIE_SECURE_MODE in {"1", "true", "yes", "on"}:
        return True
    if AUTH_COOKIE_SECURE_MODE in {"0", "false", "no", "off"}:
        return False
    return not is_local_request(request) and get_request_scheme(request) == "https"


def resolve_cookie_samesite(request: Request) -> str:
    if AUTH_COOKIE_SAMESITE_MODE in {"lax", "strict", "none"}:
        return AUTH_COOKIE_SAMESITE_MODE
    return "lax" if is_local_request(request) else "none"


def set_auth_session_cookie(response: Response, raw_token: str, request: Request) -> None:
    response.set_cookie(
        key=AUTH_SESSION_COOKIE_NAME,
        value=str(raw_token or ""),
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=resolve_cookie_secure(request),
        samesite=resolve_cookie_samesite(request),
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
    )


def clear_auth_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=AUTH_SESSION_COOKIE_NAME,
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
        secure=resolve_cookie_secure(request),
        httponly=True,
        samesite=resolve_cookie_samesite(request),
    )


def record_get(record: asyncpg.Record, key: str, default: Any = None) -> Any:
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


def validate_email(email: Any) -> str:
    normalized = normalize_email(email)
    if not normalized or not EMAIL_RE.match(normalized):
        raise ValueError("Email không hợp lệ.")
    return normalized


def validate_full_name(full_name: Any) -> str:
    cleaned = normalize_text(full_name)
    if len(cleaned) < 2:
        raise ValueError("Vui lòng nhập họ tên đầy đủ.")
    return cleaned


def validate_password(password: Any) -> str:
    password_text = str(password or "")
    has_min_length = len(password_text) >= PASSWORD_MIN_LENGTH
    has_number = any(ch.isdigit() for ch in password_text)
    has_uppercase = any(ch.isalpha() and ch.isupper() for ch in password_text)

    if not (has_min_length and has_number and has_uppercase):
        raise ValueError(PASSWORD_POLICY_MESSAGE)
    return password_text


def validate_work_unit(work_unit: Any) -> Optional[str]:
    cleaned = normalize_text(work_unit)
    return cleaned or None


def validate_position(position: Any) -> Optional[str]:
    cleaned = normalize_text(position)
    if not cleaned:
        return None
    if cleaned not in POSITION_OPTIONS:
        raise ValueError("Vị trí không nằm trong danh sách được hỗ trợ.")
    return cleaned


def derive_profile_stage(work_unit: Optional[str], position: Optional[str]) -> str:
    return "expanded" if work_unit and position else "basic"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${derived}"


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False

    try:
        algorithm, iterations_text, salt, expected_hash = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
    except (ValueError, TypeError):
        return False

    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return secrets.compare_digest(actual_hash, expected_hash)


def build_token_hash(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def get_allowed_google_client_ids() -> list[str]:
    client_ids = []
    raw_multi = os.getenv("GOOGLE_CLIENT_IDS", "")
    raw_single = os.getenv("GOOGLE_CLIENT_ID", "")

    for value in [raw_single, *raw_multi.split(",")]:
        item = value.strip()
        if item and item not in client_ids:
            client_ids.append(item)

    return client_ids


def get_auth_config_payload() -> Dict[str, Any]:
    client_ids = get_allowed_google_client_ids()
    google_library_ready = GoogleAuthRequest is not None and google_id_token is not None
    google_enabled = bool(client_ids) and google_library_ready
    password_reset_status = get_password_reset_email_status()

    return {
        "google_enabled": google_enabled,
        "google_client_id": client_ids[0] if google_enabled else None,
        "google_status": (
            "ready"
            if google_enabled
            else "missing_library"
            if client_ids and not google_library_ready
            else "missing_client_id"
        ),
        "google_library_error": GOOGLE_AUTH_IMPORT_ERROR if client_ids and not google_library_ready else "",
        "position_options": POSITION_OPTIONS,
        "position_option_groups": POSITION_OPTION_GROUPS,
        "profile_fields": {
            "required_now": ["email", "password", "full_name"],
            "optional_later": ["work_unit", "position"],
        },
        "password_policy_message": PASSWORD_POLICY_MESSAGE,
        "password_reset_enabled": is_password_reset_email_enabled(),
        "password_reset_status": password_reset_status,
    }


def is_password_reset_email_enabled() -> bool:
    return bool(SMTP_HOST and SMTP_PORT and SMTP_FROM_EMAIL)


def get_password_reset_email_status() -> str:
    if not SMTP_HOST:
        return "missing_smtp_host"
    if not SMTP_PORT:
        return "missing_smtp_port"
    if not SMTP_FROM_EMAIL:
        return "missing_from_email"
    return "ready"


def get_client_ip_from_request(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip

    return getattr(request.client, "host", "") or "unknown"


def serialize_user(record: asyncpg.Record) -> Dict[str, Any]:
    work_unit = record_get(record, "work_unit")
    position = record_get(record, "position")
    profile_stage = record_get(record, "profile_stage") or derive_profile_stage(work_unit, position)
    pending_fields = []

    if not work_unit:
        pending_fields.append("work_unit")
    if not position:
        pending_fields.append("position")

    return {
        "id": int(record["id"]),
        "email": record["email"],
        "full_name": record["full_name"],
        "work_unit": work_unit,
        "position": position,
        "auth_provider": record_get(record, "auth_provider") or "email",
        "email_verified": bool(record_get(record, "email_verified")),
        "has_password": bool(record_get(record, "password_hash")),
        "has_google": bool(record_get(record, "google_sub")),
        "profile_stage": profile_stage,
        "pending_profile_fields": pending_fields,
        "created_at": record["created_at"].isoformat() if record_get(record, "created_at") else None,
        "last_login_at": record["last_login_at"].isoformat() if record_get(record, "last_login_at") else None,
    }


async def ensure_auth_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_users (
            id BIGSERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            password_hash TEXT,
            google_sub TEXT UNIQUE,
            auth_provider TEXT NOT NULL DEFAULT 'email',
            work_unit TEXT,
            position TEXT,
            profile_stage TEXT NOT NULL DEFAULT 'basic',
            email_verified BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP
        )
        """
    )
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash TEXT")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS google_sub TEXT")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS auth_provider TEXT NOT NULL DEFAULT 'email'")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS work_unit TEXT")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS position TEXT")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS profile_stage TEXT NOT NULL DEFAULT 'basic'")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP")
    await conn.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP")
    await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_google_sub ON app_users (google_sub)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_app_users_auth_provider ON app_users (auth_provider)")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_user_sessions (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            last_used_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            user_agent TEXT
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_app_user_sessions_user_id ON app_user_sessions (user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_app_user_sessions_expires_at ON app_user_sessions (expires_at)")
    await conn.execute("DELETE FROM app_user_sessions WHERE expires_at < CURRENT_TIMESTAMP")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_password_reset_tokens (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            requested_ip TEXT,
            user_agent TEXT
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_app_password_reset_tokens_user_id ON app_password_reset_tokens (user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_app_password_reset_tokens_expires_at ON app_password_reset_tokens (expires_at)")
    await conn.execute("DELETE FROM app_password_reset_tokens WHERE expires_at < CURRENT_TIMESTAMP OR used_at IS NOT NULL")


async def create_session_for_user(conn: asyncpg.Connection, user_id: int, request: Request) -> str:
    raw_token = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)
    await conn.execute(
        """
        INSERT INTO app_user_sessions (user_id, token_hash, expires_at, ip_address, user_agent)
        VALUES ($1, $2, $3, $4, $5)
        """,
        user_id,
        build_token_hash(raw_token),
        expires_at,
        get_client_ip_from_request(request),
        request.headers.get("user-agent", "")[:500],
    )
    await conn.execute(
        """
        UPDATE app_users
        SET last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = $1
        """,
        user_id,
    )
    return raw_token


async def fetch_user_by_email(conn: asyncpg.Connection, email: str) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM app_users WHERE email = $1", email)


async def fetch_user_by_google_sub(conn: asyncpg.Connection, google_sub: str) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM app_users WHERE google_sub = $1", google_sub)


async def fetch_user_by_id(conn: asyncpg.Connection, user_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM app_users WHERE id = $1", user_id)


async def delete_password_reset_tokens_for_user(conn: asyncpg.Connection, user_id: int) -> None:
    await conn.execute("DELETE FROM app_password_reset_tokens WHERE user_id = $1", user_id)


async def revoke_user_sessions(conn: asyncpg.Connection, user_id: int, *, except_token_hash: Optional[str] = None) -> None:
    if except_token_hash:
        await conn.execute(
            "DELETE FROM app_user_sessions WHERE user_id = $1 AND token_hash <> $2",
            user_id,
            except_token_hash,
        )
        return
    await conn.execute("DELETE FROM app_user_sessions WHERE user_id = $1", user_id)


async def register_with_email(
    conn: asyncpg.Connection,
    request: Request,
    email: Any,
    password: Any,
    full_name: Any,
    work_unit: Any = None,
    position: Any = None,
) -> Dict[str, Any]:
    normalized_email = validate_email(email)
    clean_password = validate_password(password)
    clean_full_name = validate_full_name(full_name)
    clean_work_unit = validate_work_unit(work_unit)
    clean_position = validate_position(position)
    password_hash = hash_password(clean_password)
    profile_stage = derive_profile_stage(clean_work_unit, clean_position)

    existing_user = await fetch_user_by_email(conn, normalized_email)
    if existing_user:
        if record_get(existing_user, "password_hash"):
            raise ValueError("Email này đã được đăng ký. Vui lòng đăng nhập.")

        merged_work_unit = clean_work_unit or record_get(existing_user, "work_unit")
        merged_position = clean_position or record_get(existing_user, "position")
        profile_stage = derive_profile_stage(merged_work_unit, merged_position)

        user = await conn.fetchrow(
            """
            UPDATE app_users
            SET
                full_name = COALESCE(NULLIF($2, ''), full_name),
                password_hash = $3,
                auth_provider = CASE WHEN google_sub IS NOT NULL THEN 'hybrid' ELSE 'email' END,
                work_unit = COALESCE($4, work_unit),
                position = COALESCE($5, position),
                profile_stage = $6,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING *
            """,
            existing_user["id"],
            clean_full_name,
            password_hash,
            clean_work_unit,
            clean_position,
            profile_stage,
        )
    else:
        user = await conn.fetchrow(
            """
            INSERT INTO app_users (
                email,
                full_name,
                password_hash,
                auth_provider,
                work_unit,
                position,
                profile_stage,
                email_verified
            )
            VALUES ($1, $2, $3, 'email', $4, $5, $6, FALSE)
            RETURNING *
            """,
            normalized_email,
            clean_full_name,
            password_hash,
            clean_work_unit,
            clean_position,
            profile_stage,
        )

    token = await create_session_for_user(conn, int(user["id"]), request)
    return {
        "token": token,
        "user": serialize_user(user),
    }


async def login_with_email(
    conn: asyncpg.Connection,
    request: Request,
    email: Any,
    password: Any,
) -> Dict[str, Any]:
    normalized_email = validate_email(email)
    user = await fetch_user_by_email(conn, normalized_email)

    if not user or not verify_password(str(password or ""), record_get(user, "password_hash")):
        raise ValueError("Email hoặc mật khẩu chưa đúng.")

    token = await create_session_for_user(conn, int(user["id"]), request)
    refreshed_user = await fetch_user_by_id(conn, int(user["id"]))
    return {
        "token": token,
        "user": serialize_user(refreshed_user or user),
    }


def _verify_google_credential_sync(credential: str, allowed_client_ids: list[str]) -> Dict[str, Any]:
    if GoogleAuthRequest is None or google_id_token is None:
        raise ValueError("Thiếu thư viện google-auth. Vui lòng cài dependency trước khi dùng Google sign-in.")

    last_error: Optional[Exception] = None
    request = GoogleAuthRequest()

    for client_id in allowed_client_ids:
        try:
            payload = google_id_token.verify_oauth2_token(credential, request, audience=client_id)
            if payload:
                return payload
        except Exception as exc:  # pragma: no cover - depends on Google response
            last_error = exc

    raise ValueError("Không xác minh được đăng nhập Google.") from last_error


async def login_with_google(
    conn: asyncpg.Connection,
    request: Request,
    credential: Any,
) -> Dict[str, Any]:
    token_credential = str(credential or "").strip()
    if not token_credential:
        raise ValueError("Thiếu Google credential.")

    allowed_client_ids = get_allowed_google_client_ids()
    if not allowed_client_ids:
        raise ValueError("Đăng nhập Google chưa được cấu hình trên hệ thống.")

    payload = await asyncio.to_thread(_verify_google_credential_sync, token_credential, allowed_client_ids)

    email = validate_email(payload.get("email"))
    google_sub = normalize_text(payload.get("sub"))
    full_name = validate_full_name(payload.get("name") or payload.get("given_name") or email.split("@")[0])
    email_verified = bool(payload.get("email_verified"))

    if not google_sub:
        raise ValueError("Google credential không chứa định danh người dùng.")
    if not email_verified:
        raise ValueError("Tài khoản Google chưa xác minh email.")

    user = await fetch_user_by_google_sub(conn, google_sub)
    if user:
        user = await conn.fetchrow(
            """
            UPDATE app_users
            SET
                email = $2,
                full_name = COALESCE(NULLIF(full_name, ''), $3),
                email_verified = TRUE,
                auth_provider = CASE WHEN password_hash IS NOT NULL THEN 'hybrid' ELSE 'google' END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING *
            """,
            user["id"],
            email,
            full_name,
        )
    else:
        by_email = await fetch_user_by_email(conn, email)
        if by_email:
            user = await conn.fetchrow(
                """
                UPDATE app_users
                SET
                    google_sub = $2,
                    full_name = COALESCE(NULLIF(full_name, ''), $3),
                    email_verified = TRUE,
                    auth_provider = CASE WHEN password_hash IS NOT NULL THEN 'hybrid' ELSE 'google' END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                RETURNING *
                """,
                by_email["id"],
                google_sub,
                full_name,
            )
        else:
            user = await conn.fetchrow(
                """
                INSERT INTO app_users (
                    email,
                    full_name,
                    google_sub,
                    auth_provider,
                    profile_stage,
                    email_verified
                )
                VALUES ($1, $2, $3, 'google', 'basic', TRUE)
                RETURNING *
                """,
                email,
                full_name,
                google_sub,
            )

    session_token = await create_session_for_user(conn, int(user["id"]), request)
    return {
        "token": session_token,
        "user": serialize_user(user),
    }


def extract_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header:
        return None

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def extract_session_token(request: Request) -> Optional[str]:
    cookie_token = (request.cookies.get(AUTH_SESSION_COOKIE_NAME) or "").strip()
    if cookie_token:
        return cookie_token
    return extract_bearer_token(request)


async def get_authenticated_user(conn: asyncpg.Connection, raw_token: str) -> Optional[Dict[str, Any]]:
    if not raw_token:
        return None

    row = await conn.fetchrow(
        """
        SELECT
            u.*,
            s.id AS session_id,
            s.expires_at
        FROM app_user_sessions s
        JOIN app_users u ON u.id = s.user_id
        WHERE s.token_hash = $1
        """,
        build_token_hash(raw_token),
    )

    if not row:
        return None

    expires_at = record_get(row, "expires_at")
    if expires_at and expires_at <= datetime.utcnow():
        await conn.execute("DELETE FROM app_user_sessions WHERE id = $1", row["session_id"])
        return None

    await conn.execute(
        "UPDATE app_user_sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = $1",
        row["session_id"],
    )
    return serialize_user(row)


async def require_authenticated_user(conn: asyncpg.Connection, request: Request) -> Dict[str, Any]:
    raw_token = extract_session_token(request)
    user = await get_authenticated_user(conn, raw_token or "")
    if user:
        return user
    raise HTTPException(status_code=401, detail="Bạn cần đăng nhập để tiếp tục.")


async def logout_current_session(conn: asyncpg.Connection, request: Request) -> None:
    raw_token = extract_session_token(request)
    if not raw_token:
        return
    await conn.execute(
        "DELETE FROM app_user_sessions WHERE token_hash = $1",
        build_token_hash(raw_token),
    )


def build_password_reset_link(request: Request, raw_token: str) -> str:
    base_url = (
        PASSWORD_RESET_BASE_URL
        or FRONTEND_BASE_URL
        or request.headers.get("origin", "").strip()
        or f"{get_request_scheme(request)}://{request.headers.get('host', '').strip()}"
    ).rstrip("/")
    if not base_url or "://" not in base_url:
        raise ValueError("Thiếu cấu hình URL frontend để tạo liên kết đặt lại mật khẩu.")
    query = urlencode({"reset_password_token": raw_token})
    return f"{base_url}/?{query}"


def _send_password_reset_email_sync(recipient_email: str, recipient_name: str, reset_link: str) -> None:
    if not is_password_reset_email_enabled():
        raise ValueError("Chức năng gửi email đặt lại mật khẩu chưa được cấu hình.")

    message = EmailMessage()
    message["Subject"] = "[BIDFinder] - Thông báo đặt lại mật khẩu"
    message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    message["To"] = recipient_email
    message.set_content(
        "\n".join(
            [
                f"Xin chào {recipient_name or recipient_email},",
                "",
                "Chúng tôi đã nhận được yêu cầu đặt lại mật khẩu cho tài khoản BIDFinder của bạn.",
                f"Vui lòng mở liên kết sau để tạo mật khẩu mới trong {PASSWORD_RESET_TTL_MINUTES} phút:",
                reset_link,
                "",
               
            ]
        )
    )

    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        if SMTP_USE_TLS:
            smtp.starttls()
            smtp.ehlo()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


async def request_password_reset(conn: asyncpg.Connection, request: Request, email: Any) -> None:
    normalized_email = validate_email(email)
    user = await fetch_user_by_email(conn, normalized_email)

    if not user:
        return

    await delete_password_reset_tokens_for_user(conn, int(user["id"]))

    raw_token = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES)
    await conn.execute(
        """
        INSERT INTO app_password_reset_tokens (user_id, token_hash, expires_at, requested_ip, user_agent)
        VALUES ($1, $2, $3, $4, $5)
        """,
        int(user["id"]),
        build_token_hash(raw_token),
        expires_at,
        get_client_ip_from_request(request),
        request.headers.get("user-agent", "")[:500],
    )
    await asyncio.to_thread(
        _send_password_reset_email_sync,
        normalized_email,
        record_get(user, "full_name") or normalized_email,
        build_password_reset_link(request, raw_token),
    )


async def reset_password_with_token(
    conn: asyncpg.Connection,
    request: Request,
    *,
    token: Any,
    new_password: Any,
) -> Dict[str, Any]:
    raw_token = str(token or "").strip()
    if not raw_token:
        raise ValueError("Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.")

    password_text = validate_password(new_password)
    row = await conn.fetchrow(
        """
        SELECT
            t.id,
            t.user_id,
            t.expires_at,
            t.used_at,
            u.*
        FROM app_password_reset_tokens t
        JOIN app_users u ON u.id = t.user_id
        WHERE t.token_hash = $1
        """,
        build_token_hash(raw_token),
    )
    if not row or record_get(row, "used_at"):
        raise ValueError("Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.")

    expires_at = record_get(row, "expires_at")
    if expires_at and expires_at <= datetime.utcnow():
        await conn.execute("DELETE FROM app_password_reset_tokens WHERE id = $1", row["id"])
        raise ValueError("Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.")

    updated_user = await conn.fetchrow(
        """
        UPDATE app_users
        SET
            password_hash = $2,
            auth_provider = CASE WHEN google_sub IS NOT NULL THEN 'hybrid' ELSE 'email' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $1
        RETURNING *
        """,
        int(row["user_id"]),
        hash_password(password_text),
    )
    await conn.execute(
        "UPDATE app_password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = $1",
        row["id"],
    )
    await revoke_user_sessions(conn, int(row["user_id"]))
    await delete_password_reset_tokens_for_user(conn, int(row["user_id"]))
    session_token = await create_session_for_user(conn, int(row["user_id"]), request)
    return {
        "token": session_token,
        "user": serialize_user(updated_user),
    }


async def change_password(
    conn: asyncpg.Connection,
    request: Request,
    *,
    user_id: int,
    current_password: Any = None,
    new_password: Any,
) -> Dict[str, Any]:
    user = await fetch_user_by_id(conn, user_id)
    if not user:
        raise ValueError("Không tìm thấy người dùng.")

    existing_password_hash = record_get(user, "password_hash")
    if existing_password_hash and not verify_password(str(current_password or ""), existing_password_hash):
        raise ValueError("Mật khẩu hiện tại chưa đúng.")
    if existing_password_hash and verify_password(str(new_password or ""), existing_password_hash):
        raise ValueError("Mật khẩu mới cần khác mật khẩu hiện tại.")

    updated_user = await conn.fetchrow(
        """
        UPDATE app_users
        SET
            password_hash = $2,
            auth_provider = CASE WHEN google_sub IS NOT NULL THEN 'hybrid' ELSE 'email' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $1
        RETURNING *
        """,
        user_id,
        hash_password(validate_password(new_password)),
    )
    current_token_hash = build_token_hash(extract_session_token(request) or "")
    await revoke_user_sessions(conn, user_id, except_token_hash=current_token_hash if current_token_hash else None)
    await delete_password_reset_tokens_for_user(conn, user_id)
    return serialize_user(updated_user)


async def update_user_profile(
    conn: asyncpg.Connection,
    user_id: int,
    *,
    full_name: Any = None,
    work_unit: Any = None,
    position: Any = None,
) -> Dict[str, Any]:
    current_user = await fetch_user_by_id(conn, user_id)
    if not current_user:
        raise ValueError("Không tìm thấy người dùng.")

    next_full_name = validate_full_name(full_name) if full_name is not None else current_user["full_name"]
    next_work_unit = validate_work_unit(work_unit) if work_unit is not None else record_get(current_user, "work_unit")
    next_position = validate_position(position) if position is not None else record_get(current_user, "position")
    next_profile_stage = derive_profile_stage(next_work_unit, next_position)

    updated_user = await conn.fetchrow(
        """
        UPDATE app_users
        SET
            full_name = $2,
            work_unit = $3,
            position = $4,
            profile_stage = $5,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $1
        RETURNING *
        """,
        user_id,
        next_full_name,
        next_work_unit,
        next_position,
        next_profile_stage,
    )

    return serialize_user(updated_user)
