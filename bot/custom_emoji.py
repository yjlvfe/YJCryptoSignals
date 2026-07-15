"""
📱 Custom Emoji Manager — التقاط وتحويل الإيموجي المتحرك تلقائياً
"""
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("crypto-signal-emoji")

EMOJI_MAP_FILE = Path("/root/.crypto-signal-bot/custom_emoji_map.json")

# خريطة الإيموجي المميز (رمز → custom_emoji_id)
_custom_emoji_map = {}
_loaded = False


def _load_map():
    """تحميل الخريطة من الملف"""
    global _custom_emoji_map, _loaded
    if _loaded:
        return
    try:
        if EMOJI_MAP_FILE.exists():
            _custom_emoji_map = json.loads(EMOJI_MAP_FILE.read_text())
            logger.info(f"📦 Loaded {len(_custom_emoji_map)} custom emoji mappings")
    except Exception as e:
        logger.warning(f"Failed to load emoji map: {e}")
    _loaded = True


def _save_map():
    """حفظ الخريطة إلى الملف"""
    try:
        EMOJI_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        EMOJI_MAP_FILE.write_text(json.dumps(_custom_emoji_map, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"Failed to save emoji map: {e}")


def register_custom_emoji(emoji_char: str, custom_emoji_id: str):
    """تسجيل إيموجي متحرك: ربط الرمز بالـ ID"""
    _load_map()
    if _custom_emoji_map.get(emoji_char) != custom_emoji_id:
        _custom_emoji_map[emoji_char] = custom_emoji_id
        _save_map()
        logger.info(f"✅ Registered custom emoji: {emoji_char} -> {custom_emoji_id}")


def extract_emojis_from_message(text: str, entities: list) -> list:
    """استخراج custom_emoji entities من رسالة واردة وتسجيلها"""
    _load_map()
    newly_registered = []
    for e in entities:
        if e.get("type") == "custom_emoji":
            cid = e.get("custom_emoji_id")
            offset = e.get("offset", 0)
            length = e.get("length", 0)
            try:
                utf16 = text.encode("utf-16-le")
                byte_start = offset * 2
                byte_end = (offset + length) * 2
                emoji_bytes = utf16[byte_start:byte_end]
                emoji_char = emoji_bytes.decode("utf-16-le")
                if not _custom_emoji_map.get(emoji_char):
                    register_custom_emoji(emoji_char, cid)
                    newly_registered.append(emoji_char)
            except Exception as ex:
                logger.debug(f"Failed to extract emoji at off={offset}: {ex}")
    return newly_registered


def _utf16_len(s: str) -> int:
    """حساب طول النص بوحدات UTF-16 (كما يستخدمها Telegram في entity offsets)"""
    return len(s.encode('utf-16-le')) // 2


def build_entities(text: str, emoji_map: dict) -> tuple:
    """
    يحول نص Markdown إلى (نص نظيف, entities) مع دعم custom emoji.
    
    يتعامل مع:
      **bold** → type=bold
      *italic* → type=italic
      `code` → type=code
      ```block``` → type=pre
      [text](url) → type=text_link
      إيموجي مسجل → type=custom_emoji
    
    الـ entities جاهزة للإرسال مع sendMessage (بدون parse_mode).
    Offsets محسوبة بوحدات UTF-16 كما يتطلب Telegram.
    """
    entities = []
    clean_parts = []
    utf16_pos = 0  # موقع الكتابة بوحدات UTF-16 في النص النظيف

    i = 0
    n = len(text)

    while i < n:
        # 1) Code block ```...```
        if text[i:i+3] == '```':
            end = text.find('```', i + 3)
            if end != -1:
                content = text[i + 3:end]
                nl = content.find('\n')
                if nl != -1:
                    content = content[nl + 1:]
                content = content.rstrip('\n')
                clen = _utf16_len(content)
                clean_parts.append(content)
                entities.append({"type": "pre", "offset": utf16_pos, "length": clen})
                utf16_pos += clen
                i = end + 3
                continue

        # 2) Inline code `...`
        if text[i] == '`' and text[i:i+3] != '```':
            end = text.find('`', i + 1)
            if end != -1:
                content = text[i + 1:end]
                clen = _utf16_len(content)
                clean_parts.append(content)
                entities.append({"type": "code", "offset": utf16_pos, "length": clen})
                utf16_pos += clen
                i = end + 1
                continue

        # 3) Bold **...**
        if text[i:i+2] == '**':
            end = text.find('**', i + 2)
            if end != -1:
                content = text[i + 2:end]
                clen = _utf16_len(content)
                clean_parts.append(content)
                entities.append({"type": "bold", "offset": utf16_pos, "length": clen})
                utf16_pos += clen
                i = end + 2
                continue

        # 4) Italic *...* (مفردة * وليست **)
        if text[i] == '*' and text[i:i+2] != '**':
            end = -1
            j = i + 1
            while j < n:
                if text[j] == '*' and text[j:j+2] != '**':
                    end = j
                    break
                j += 1
            if end != -1:
                content = text[i + 1:end]
                if content and not content.isspace():
                    clen = _utf16_len(content)
                    clean_parts.append(content)
                    entities.append({"type": "italic", "offset": utf16_pos, "length": clen})
                    utf16_pos += clen
                    i = end + 1
                    continue
                else:
                    # لا نية Italic (مثلاً علامة ضرب *) نعاملها كنص عادي
                    pass

        # 5) Link [text](url)
        if text[i] == '[':
            close_b = text.find(']', i)
            if close_b != -1 and text[close_b + 1:close_b + 2] == '(':
                close_p = text.find(')', close_b + 2)
                if close_p != -1:
                    link_text = text[i + 1:close_b]
                    url = text[close_b + 2:close_p]
                    clen = _utf16_len(link_text)
                    clean_parts.append(link_text)
                    entities.append({
                        "type": "text_link",
                        "offset": utf16_pos,
                        "length": clen,
                        "url": url
                    })
                    utf16_pos += clen
                    i = close_p + 1
                    continue

        # 6) لا Markdown هنا → char عادي
        ch = text[i]

        # تخطي VS16 المنفرد
        if ch == '\uFE0F':
            i += 1
            continue

        # التحقق من custom emoji
        ch_clean = ch.replace('\uFE0F', '')
        cid = emoji_map.get(ch_clean) or emoji_map.get(ch)
        ch_utf16_len = _utf16_len(ch)

        if cid:
            clean_parts.append(ch)
            entities.append({
                "type": "custom_emoji",
                "offset": utf16_pos,
                "length": ch_utf16_len,
                "custom_emoji_id": cid
            })
        else:
            clean_parts.append(ch)

        utf16_pos += ch_utf16_len
        i += 1

    return ''.join(clean_parts), entities


def apply_custom_emojis(text: str) -> tuple:
    """بقاء للتوافق — يحول النص إلى (نص نظيف, entities) باستخدام build_entities"""
    _load_map()
    return build_entities(text, _custom_emoji_map)


def get_emoji_id(emoji_char: str) -> str:
    """جلب الـ custom_emoji_id لإيموجي معين"""
    _load_map()
    return _custom_emoji_map.get(emoji_char)


def get_all_mappings() -> dict:
    """جلب كل الخرائط المسجلة"""
    _load_map()
    return dict(_custom_emoji_map)
