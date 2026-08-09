"""安全检测共用的 Unicode 同形字符归一化。

该骨架只用于检测，不用于改写或展示用户内容。NFKC 能处理全角字符，但不会折叠大量
希腊字母、西里尔字母和其他书写系统中的同形字符。主映射使用
``confusable-homoglyphs`` 随包分发的 Unicode confusables 数据；显式映射只保留为旧数据
兼容层，避免依赖数据更新改变已经覆盖的安全关键词。
"""

from __future__ import annotations

import unicodedata

from confusable_homoglyphs import confusables

CONFUSABLE_TRANSLATION = str.maketrans(
    {
        "ɑ": "a",
        "а": "a",
        "ᴀ": "a",
        "Ь": "b",
        "β": "b",
        "ʙ": "b",
        "с": "c",
        "ϲ": "c",
        "ᴄ": "c",
        "ԁ": "d",
        "ᴅ": "d",
        "е": "e",
        "ε": "e",
        "ᴇ": "e",
        "ꜰ": "f",
        "ғ": "f",
        "ɡ": "g",
        "ɢ": "g",
        "һ": "h",
        "ʜ": "h",
        "і": "i",
        "ɪ": "i",
        "ј": "j",
        "ᴊ": "j",
        "κ": "k",
        "ᴋ": "k",
        "ℓ": "l",
        "ʟ": "l",
        "м": "m",
        "ᴍ": "m",
        "ո": "n",
        "ɴ": "n",
        "ο": "o",
        "о": "o",
        "ᴏ": "o",
        "р": "p",
        "ᴘ": "p",
        "ԛ": "q",
        "գ": "q",
        "ʀ": "r",
        "ѕ": "s",
        "ꜱ": "s",
        "т": "t",
        "ᴛ": "t",
        "υ": "u",
        "ᴜ": "u",
        "ѵ": "v",
        "ᴠ": "v",
        "ԝ": "w",
        "ᴡ": "w",
        "х": "x",
        "ⅹ": "x",
        "у": "y",
        "ʏ": "y",
        "ᴢ": "z",
    }
)


def confusableSkeleton(value: str) -> str:
    """返回适合安全规则比较的 NFKC + Unicode 同形字符骨架。

    只接受由单个同形字符确定映射出的 ASCII 字母或数字。这样既覆盖完整数据集，也不会
    把标点、组合串或非拉丁自然语言任意改写成安全关键词。
    """

    normalized = unicodedata.normalize("NFKC", value).casefold()
    translated: list[str] = []
    for character in normalized:
        # ASCII 本身是所有安全规则的稳定基线，绝不能再按 Unicode 反向同形关系
        # 改写（例如把数字 ``1`` 变成字母 ``l``）；否则电话、银行卡和社保号检测会漏报。
        if character.isascii():
            translated.append(character)
            continue

        explicit = character.translate(CONFUSABLE_TRANSLATION)
        if explicit != character:
            translated.append(explicit)
            continue

        replacement = character
        for candidate in confusables.confusables_data.get(character, ()):
            candidateText = str(candidate.get("c", "")).casefold()
            if len(candidateText) == 1 and candidateText.isascii() and candidateText.isalnum():
                replacement = candidateText
                break
        translated.append(replacement)

    return "".join(translated)
