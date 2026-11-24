"""Rule-based extraction from the message: the search arguments of Stage 1A (replaced by LLM tool selection in 1C), and
the skin type every path uses when the request has none (ADR-196).

>>> extract("건성 피부에 끈적이지 않는 수분크림 중 내일 도착 가능하고 3만원 이하인 상품 추천해 줘")
('수분크림', 30000)
>>> extract("촉촉한 거 뭐 없나")
('촉촉', None)
>>> extract("촉촉한 토너 25,000원까지")
('토너', 25000)
>>> extract("1.5만원 아래 세럼")
('세럼', 15000)
>>> extract("3만원 이상 크림"), extract("안녕하세요")
(('크림', None), (None, None))
>>> extract("3만원 미만 크림")
('크림', 29999)
>>> extract("스킨케어 추천해줘"), extract("젤리 같은 제형 말고")
((None, None), (None, None))
>>> extract("토너 99999999999원 이하"), extract("토너 99999만원 이하")
(('토너', None), ('토너', None))
>>> extract("1.2.3만원 이하 토너"), extract("토너 " + "9" * 5000 + "원 이하")
(('토너', None), ('토너', None))
>>> skin_type_in("건성 피부에 끈적이지 않는 수분크림"), skin_type_in("악건성인데 크림"), skin_type_in("민감성 토너")
('dry', 'dry', 'sensitive')
>>> skin_type_in("건성 아니고 지성인데"), skin_type_in("수부지 크림"), skin_type_in("촉촉한 토너")
(None, None, None)
"""

import re

# Longer words first so "수분크림" wins over "크림". Product types win over effects.
# No "스킨"/"젤": they match inside "스킨케어"/"젤리".
PRODUCT_TYPES = ["수분크림", "선크림", "크림", "토너", "세럼", "앰플", "에센스", "로션", "미스트", "패드"]
EFFECTS = ["촉촉", "보습", "진정", "수분", "산뜻", "저자극", "트러블", "각질", "미백"]

# The four values /chat accepts as skinType. A message naming more than one ("건성 아니고 지성") names none.
SKIN_TYPES = {"건성": "dry", "지성": "oily", "복합성": "combination", "민감성": "sensitive"}

PRICE_LIMIT = 100_000_000
# Digit counts are capped and a number cannot start inside a longer one, so absurd input never reaches int().
MAX_PRICE = re.compile(r"(?<![\d.,])(\d{1,9}(?:[.,]\d{1,9}){0,3})\s*(만\s*)?원\s*(이하|까지|아래|미만|안쪽)")


def extract(message: str) -> tuple[str | None, int | None]:
    q = next((word for word in PRODUCT_TYPES + EFFECTS if word in message), None)
    return q, _max_price(message)


def skin_type_in(message: str) -> str | None:
    found = {value for word, value in SKIN_TYPES.items() if word in message}
    return found.pop() if len(found) == 1 else None


def _max_price(message: str) -> int | None:
    match = MAX_PRICE.search(message)
    if not match:
        return None
    number, man, bound = match.groups()
    try:
        if man:
            price = round(float(number.replace(",", "")) * 10000)
        else:
            price = int(number.replace(",", "").replace(".", ""))
    except ValueError:
        return None
    if price > PRICE_LIMIT:
        return None
    return price - 1 if bound == "미만" else price
