"""Backend error-string localization — in-process catalog + weighted Accept-Language resolver."""

from __future__ import annotations

from fastapi import Header

# Supported response languages. `zh-Hans` is the canonical Simplified-Chinese code;
# any `zh` subtag (zh-CN/zh-SG/zh-TW) normalizes to it in `resolve_lang`.
SUPPORTED = ("en", "de", "fr", "es", "it", "pt", "nl", "ru", "pl", "zh-Hans", "ja", "ko")
DEFAULT = "en"

# Catalog of the known static error literals (one code per literal) translated across all
# 12 supported languages. English values match the current route literals exactly so the
# fallback is an identity (D-15: AI-generated translations shipped final).
MESSAGES: dict[str, dict[str, str]] = {
    "server_not_found": {
        "en": "Server not found",
        "de": "Server nicht gefunden",
        "fr": "Serveur introuvable",
        "es": "Servidor no encontrado",
        "it": "Server non trovato",
        "pt": "Servidor não encontrado",
        "nl": "Server niet gevonden",
        "ru": "Сервер не найден",
        "pl": "Nie znaleziono serwera",
        "zh-Hans": "未找到服务器",
        "ja": "サーバーが見つかりません",
        "ko": "서버를 찾을 수 없습니다",
    },
    "invalid_host": {
        "en": "Invalid host address",
        "de": "Ungültige Hostadresse",
        "fr": "Adresse d'hôte invalide",
        "es": "Dirección de host no válida",
        "it": "Indirizzo host non valido",
        "pt": "Endereço de host inválido",
        "nl": "Ongeldig hostadres",
        "ru": "Недопустимый адрес узла",
        "pl": "Nieprawidłowy adres hosta",
        "zh-Hans": "主机地址无效",
        "ja": "ホストアドレスが無効です",
        "ko": "잘못된 호스트 주소",
    },
    "profile_not_found": {
        "en": "Profile not found",
        "de": "Profil nicht gefunden",
        "fr": "Profil introuvable",
        "es": "Perfil no encontrado",
        "it": "Profilo non trovato",
        "pt": "Perfil não encontrado",
        "nl": "Profiel niet gevonden",
        "ru": "Профиль не найден",
        "pl": "Nie znaleziono profilu",
        "zh-Hans": "未找到配置文件",
        "ja": "プロファイルが見つかりません",
        "ko": "프로필을 찾을 수 없습니다",
    },
    "no_fields_to_update": {
        "en": "No fields to update",
        "de": "Keine Felder zum Aktualisieren",
        "fr": "Aucun champ à mettre à jour",
        "es": "No hay campos para actualizar",
        "it": "Nessun campo da aggiornare",
        "pt": "Nenhum campo para atualizar",
        "nl": "Geen velden om bij te werken",
        "ru": "Нет полей для обновления",
        "pl": "Brak pól do zaktualizowania",
        "zh-Hans": "没有要更新的字段",
        "ja": "更新するフィールドがありません",
        "ko": "업데이트할 필드가 없습니다",
    },
    "cannot_delete_preset": {
        "en": "Cannot delete preset profiles",
        "de": "Voreingestellte Profile können nicht gelöscht werden",
        "fr": "Impossible de supprimer les profils prédéfinis",
        "es": "No se pueden eliminar los perfiles predefinidos",
        "it": "Impossibile eliminare i profili predefiniti",
        "pt": "Não é possível excluir perfis predefinidos",
        "nl": "Voorinstellingsprofielen kunnen niet worden verwijderd",
        "ru": "Невозможно удалить предустановленные профили",
        "pl": "Nie można usunąć profili wstępnie ustawionych",
        "zh-Hans": "无法删除预设配置文件",
        "ja": "プリセットプロファイルは削除できません",
        "ko": "사전 설정 프로필은 삭제할 수 없습니다",
    },
    "profile_id_required": {
        "en": "profile_id required for fanpilot mode",
        "de": "profile_id für den FanPilot-Modus erforderlich",
        "fr": "profile_id requis pour le mode fanpilot",
        "es": "profile_id requerido para el modo fanpilot",
        "it": "profile_id richiesto per la modalità fanpilot",
        "pt": "profile_id necessário para o modo fanpilot",
        "nl": "profile_id vereist voor fanpilot-modus",
        "ru": "Для режима fanpilot требуется profile_id",
        "pl": "profile_id wymagane dla trybu fanpilot",
        "zh-Hans": "fanpilot 模式需要 profile_id",
        "ja": "fanpilot モードには profile_id が必要です",
        "ko": "fanpilot 모드에는 profile_id가 필요합니다",
    },
    "module_not_found": {
        "en": "Module not found",
        "de": "Modul nicht gefunden",
        "fr": "Module introuvable",
        "es": "Módulo no encontrado",
        "it": "Modulo non trovato",
        "pt": "Módulo não encontrado",
        "nl": "Module niet gevonden",
        "ru": "Модуль не найден",
        "pl": "Nie znaleziono modułu",
        "zh-Hans": "未找到模块",
        "ja": "モジュールが見つかりません",
        "ko": "모듈을 찾을 수 없습니다",
    },
    "invalid_credentials": {
        "en": "Invalid credentials",
        "de": "Ungültige Anmeldedaten",
        "fr": "Identifiants invalides",
        "es": "Credenciales no válidas",
        "it": "Credenziali non valide",
        "pt": "Credenciais inválidas",
        "nl": "Ongeldige inloggegevens",
        "ru": "Неверные учётные данные",
        "pl": "Nieprawidłowe dane logowania",
        "zh-Hans": "凭据无效",
        "ja": "資格情報が無効です",
        "ko": "잘못된 자격 증명",
    },
    "user_already_exists": {
        "en": "User already exists",
        "de": "Benutzer existiert bereits",
        "fr": "L'utilisateur existe déjà",
        "es": "El usuario ya existe",
        "it": "L'utente esiste già",
        "pt": "O usuário já existe",
        "nl": "Gebruiker bestaat al",
        "ru": "Пользователь уже существует",
        "pl": "Użytkownik już istnieje",
        "zh-Hans": "用户已存在",
        "ja": "ユーザーはすでに存在します",
        "ko": "사용자가 이미 존재합니다",
    },
    "too_many_attempts": {
        "en": "Too many failed attempts. Try again later.",
        "de": "Zu viele fehlgeschlagene Versuche. Versuchen Sie es später erneut.",
        "fr": "Trop de tentatives échouées. Réessayez plus tard.",
        "es": "Demasiados intentos fallidos. Inténtelo de nuevo más tarde.",
        "it": "Troppi tentativi falliti. Riprova più tardi.",
        "pt": "Muitas tentativas falhadas. Tente novamente mais tarde.",
        "nl": "Te veel mislukte pogingen. Probeer het later opnieuw.",
        "ru": "Слишком много неудачных попыток. Повторите попытку позже.",
        "pl": "Zbyt wiele nieudanych prób. Spróbuj ponownie później.",
        "zh-Hans": "失败尝试次数过多。请稍后再试。",
        "ja": "失敗した試行が多すぎます。後でもう一度お試しください。",
        "ko": "실패한 시도가 너무 많습니다. 나중에 다시 시도하세요.",
    },
    "use_configure_to_enable": {
        "en": "Use /api/auth/configure to enable authentication",
        "de": "Verwenden Sie /api/auth/configure, um die Authentifizierung zu aktivieren",
        "fr": "Utilisez /api/auth/configure pour activer l'authentification",
        "es": "Use /api/auth/configure para habilitar la autenticación",
        "it": "Usa /api/auth/configure per abilitare l'autenticazione",
        "pt": "Use /api/auth/configure para ativar a autenticação",
        "nl": "Gebruik /api/auth/configure om authenticatie in te schakelen",
        "ru": "Используйте /api/auth/configure для включения аутентификации",
        "pl": "Użyj /api/auth/configure, aby włączyć uwierzytelnianie",
        "zh-Hans": "使用 /api/auth/configure 启用身份验证",
        "ja": "認証を有効にするには /api/auth/configure を使用してください",
        "ko": "인증을 활성화하려면 /api/auth/configure를 사용하세요",
    },
}


def _match(tag: str) -> str | None:
    """Map a single Accept-Language tag to a SUPPORTED code, or None if unsupported.

    Exact matches win; otherwise the primary subtag is used — any `zh` primary
    normalizes to `zh-Hans` (zh-CN/zh-SG/zh-TW all resolve here).
    """
    tag = tag.strip()
    if not tag or tag == "*":
        return None
    if tag in SUPPORTED:
        return tag
    primary = tag.split("-")[0].lower()
    if primary == "zh":
        return "zh-Hans"
    if primary in SUPPORTED:
        return primary
    return None


def resolve_lang(accept_language: str | None) -> str:
    """Resolve a response language from an Accept-Language header (q-weighted).

    Honors `q=` quality values: among all entries that map to a supported language,
    the highest-q match wins (earliest entry breaks ties). Falsy, malformed, or
    fully-unsupported headers fall back to English. No external dependency.
    """
    if not accept_language:
        return DEFAULT

    best_code: str | None = None
    best_q = -1.0
    for entry in accept_language.split(","):
        parts = entry.split(";")
        tag = parts[0].strip()
        q = 1.0
        for param in parts[1:]:
            param = param.strip()
            if param.lower().startswith("q="):
                try:
                    q = float(param[2:])
                except ValueError:
                    # Malformed quality — this entry cannot win.
                    q = 0.0
        code = _match(tag)
        if code is None:
            continue
        # Strict `>` keeps the earliest entry on a q tie (stable tiebreak).
        if q > best_q:
            best_q = q
            best_code = code

    return best_code if best_code is not None else DEFAULT


def t(code: str, lang: str) -> str:
    """Look up a localized message by code, falling back to English then the raw code."""
    entry = MESSAGES.get(code, {})
    return entry.get(lang) or entry.get(DEFAULT) or code


def get_lang(accept_language: str | None = Header(default=None)) -> str:
    """FastAPI dependency: resolve the request's response language from Accept-Language."""
    return resolve_lang(accept_language)
