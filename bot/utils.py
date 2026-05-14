import re
from .config import NORMALIZE_DICT

def normalize_text(text: str) -> str:
    """Приводит текст к каноническому виду (без учёта регистра, вариаций букв)"""
    text = text.lower()
    result = []
    for ch in text:
        found = False
        for canon, variants in NORMALIZE_DICT.items():
            if ch in variants:
                result.append(canon)
                found = True
                break
        if not found:
            result.append(ch)
    return ''.join(result)

def build_pattern(word: str) -> str:
    """Создаёт регулярное выражение для поиска слова с учётом вариаций"""
    parts = []
    for ch in word:
        variants = NORMALIZE_DICT.get(ch, [ch])
        escaped = [re.escape(v) for v in variants]
        parts.append('[' + ''.join(escaped) + ']')
    return ''.join(parts)

def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2"""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in special_chars else c for c in text)

def get_user_mention(user) -> str:
    """Возвращает упоминание пользователя (@username или имя)"""
    if user.username:
        return f"@{user.username}"
    else:
        return user.first_name
