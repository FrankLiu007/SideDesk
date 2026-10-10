import re

STORE_ZH = "Chrome 网上应用店搜索 ThinkNote。"
STORE_EN = "Search ThinkNote in the Chrome Web Store."
FOLLOWUP_ZH = "Word / WPS 加载项的安装说明在 thinknote.pro/word"
FOLLOWUP_EN = "The Word add-in install steps are at thinknote.pro/word"

_URL = re.compile(
    r"https?://(?:www\.)?thinknote\.pro\S*|(?<![\w.])thinknote\.pro(?:/\S*)?",
    re.IGNORECASE,
)
_DANGLING = re.compile(r"(?:说明在|Steps:)\s*$", re.MULTILINE)


def sanitize_draft(body: str) -> str:
    text = _URL.sub("", body)
    text = _DANGLING.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chinese = re.search(r"[\u4e00-\u9fff]", text) is not None
    phrase = STORE_ZH if chinese else STORE_EN
    if STORE_ZH not in text and STORE_EN not in text:
        text = f"{text}\n\n{phrase}" if text else phrase
    return text.strip()
