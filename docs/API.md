# API 계약 — Stage 1

구현보다 먼저 고정한 계약이다. Stage 1 동안 바꾸지 않는다. 결정 근거와 버린 선택지는 Notion ADR-19에 있다.

## 공통 규칙

- 모든 경로는 `/api/v1` 아래에 둔다.
- `productId`는 우리 DB의 숫자 ID다. 무신사 상품번호는 `externalId`로 따로 저장하고 응답에 노출하지 않는다. 재수집해도 화면 계약이 깨지지 않게 한다. 최종 시연 모드(ADR-72)에서 무신사 상품 링크가 필요해지면 응답에 링크 필드를 추가한다. 아직 구현하지 않았다.
- 금액은 원 단위 정수다.
- 날짜는 `YYYY-MM-DD` 문자열이다.
- 오류 응답은 HTTP 상태 코드와 아래 본문을 함께 쓴다.

```json
{ "code": "PRODUCT_SEARCH_FAILED", "message": "상품 검색에 실패했습니다." }
```

- 페이지네이션은 두지 않는다. `limit`만 쓴다.
- 대화 기록 식별자는 두지 않는다. 저장 여부가 미정이다.

## 1. Agent API

```text
POST /api/v1/chat
```

요청

```json
{ "message": "건성 피부에 끈적이지 않는 수분크림 중 내일 도착 가능하고 3만원 이하인 상품 추천해 줘" }
```

`message`는 1자 이상 500자 이하다. 벗어나거나 없으면 400과 `{ "code": "INVALID_CHAT_REQUEST", "message": "..." }`를 반환한다.

응답

```json
{
  "answer": "조건에 맞는 상품 3개를 찾았습니다.",
  "products": [
    {
      "productId": 101,
      "name": "수분크림 A",
      "brand": "브랜드 A",
      "price": 25900,
      "reason": "건성 피부 사용자의 보습력 평가가 높고 끈적임 언급이 적습니다.",
      "evidence": [
        { "reviewId": 9001, "rating": 5, "excerpt": "건성인데 아침까지 당김 없이 촉촉해요" },
        { "reviewId": 9037, "rating": 4, "excerpt": "바르고 나서 끈적임이 거의 없어요" }
      ],
      "inventory": {
        "status": "IN_STOCK",
        "quantity": 12,
        "estimatedDeliveryDate": "2026-09-17"
      }
    }
  ]
}
```

단계별로 채워지는 값이 다르다. 필드 구조는 세 단계 내내 같다.

| 필드 | 1A 직접 REST | 1B MCP 전환 | 1C LLM 도구 선택 |
|---|---|---|---|
| `answer` | 고정 템플릿 문자열 | 고정 템플릿 문자열 | LLM 생성 문장 |
| `reason` | `null` | `null` | LLM 생성 문장 |
| `evidence` | catalog 응답 그대로 | catalog 응답 그대로 | catalog 응답 그대로 |
| `inventory` | order 응답 그대로 | order 응답 그대로 | order 응답 그대로 |

`reason`은 LLM이 `evidence`를 읽고 쓴다. `evidence` 없이 생성하지 않는다. 생성 문장과 원본 리뷰를 함께 남겨야 오작동률을 측정할 수 있다.

## 2. Catalog API

```text
GET /api/v1/products/search?q=수분크림&maxPrice=30000&limit=5
```

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `q` | O | 상품명과 리뷰 본문을 대상으로 하는 키워드 검색어 |
| `maxPrice` | X | 이 값 이하만 반환 |
| `category` | X | 카테고리 코드 6자리 하나. 이 카테고리 상품만 반환 (예: `104007` 바디케어) |
| `brand` | X | 브랜드 이름과 정확히 같은 상품만 반환 (예: `라운드랩`) |
| `excludeIngredient` | X | 성분 이름. 여러 번 줄 수 있다. 이 성분이 든 상품과 성분 정보가 없는 상품을 뺀다 (예: `향료`) |
| `limit` | X | 기본 5, 최대 20 |

응답

```json
{
  "products": [
    {
      "productId": 101,
      "name": "수분크림 A",
      "brand": "브랜드 A",
      "price": 25900,
      "evidence": [
        { "reviewId": 9001, "rating": 5, "excerpt": "건성인데 아침까지 당김 없이 촉촉해요" },
        { "reviewId": 9037, "rating": 4, "excerpt": "바르고 나서 끈적임이 거의 없어요" }
      ]
    }
  ]
}
```

- `evidence`는 상품당 최대 2개다. `q`가 리뷰 본문에 걸린 리뷰를 별점 높은 순으로 고르고, 동점이면 최신순으로 고른다. `q`가 상품명에만 걸려 리뷰 본문에 걸린 리뷰가 없는 상품은 같은 정렬로 그 상품의 전체 리뷰에서 고른다. 리뷰가 하나도 없는 상품은 결과에서 뺀다. 이 정렬 규칙은 잠정값이며 검색 품질 측정 후 바꿀 수 있다.
- `excerpt`는 80자를 넘기지 않는다. LLM 입력 토큰은 이 값에 비례한다.
- `excerpt`는 `q`가 든 문장의 처음부터 보여준다. 문장은 줄바꿈이나 띄어쓰기가 뒤따르는 `.` `!` `?`에서 나눈다. 문장 처음부터 `q`까지가 80자를 넘으면 `q` 앞쪽 단어 처음부터 `…`를 붙여 보여준다.
- 피부 타입 필터는 두지 않는다. "건성"은 리뷰 본문 키워드로 걸린다.
- `category`와 `brand`는 질문에서 LLM이 도구 인자로 채운다.
- `excludeIngredient`는 성분표의 성분 이름과 정확히 같아야 한다. LLM은 MCP 도구에서 향료·알코올·미네랄오일 중에 고르고, search-mcp가 실제 성분 이름(알코올이면 에탄올·변성알코올·알코올·아이소프로필알코올)으로 바꿔 보낸다.

### 상품·리뷰 적재 (수집기 전용)

POST /internal/products/load

수집한 상품 한 개와 그 리뷰를 적재한다. 쓰기 전용이다. 구현 시점의 예외로 공통 규칙의 `/api/v1` 접두사를 따르지 않는다.

요청: `externalId`(무신사 상품번호), `name`, `brandName`, `categoryCode`, `normalPrice`, `price`, `reviewCount`, `reviewScore`, `collectedOn`, `reviews[]`. 리뷰는 `externalId`, `content`, `grade`, `likeCount`, `optionText`, `skinType`, `skinTone`, `gender`, 키·몸무게 구간, `writtenAt`, `survey`, `collectedOn`을 가진다.

응답: `{ "productId": 101, "reviewCount": 285 }`

- 상품은 `externalId`, 리뷰는 `(productId, externalId)`로 구분한다. 같은 요청을 여러 번 보내도 결과가 같다.
- 별점이 없는 리뷰(`grade` 0)는 DB 제약(1~5)에 걸리므로 보내는 쪽에서 뺀다(ADR-65).

## 3. Inventory API

```text
POST /api/v1/inventories/check
```

요청

```json
{ "productIds": [101, 102, 999] }
```

응답

```json
{
  "inventories": [
    { "productId": 101, "status": "IN_STOCK",     "quantity": 12,   "estimatedDeliveryDate": "2026-09-17" },
    { "productId": 102, "status": "OUT_OF_STOCK", "quantity": 0,    "estimatedDeliveryDate": null },
    { "productId": 999, "status": "NOT_FOUND",    "quantity": null, "estimatedDeliveryDate": null }
  ]
}
```

- 요청한 `productIds`는 빠짐없이 전부 반환한다. 순서는 보장하지 않는다.
- 한 번에 최대 20개를 요청한다.

| status | 의미 | 반환하는 곳 |
|---|---|---|
| `IN_STOCK` | 재고 1개 이상 | order-service |
| `OUT_OF_STOCK` | 재고 0개 | order-service |
| `NOT_FOUND` | order DB에 해당 상품의 재고 레코드가 없음 | order-service |
| `UNKNOWN` | order-service 호출이 실패해서 확인하지 못함 | agent-service |

order-service는 `UNKNOWN`을 반환하지 않는다. 호출 실패를 품절로 표시하지 않으려고 agent가 채우는 값이다.

### 재고 적재 (수집기 전용)

POST /api/v1/internal/inventories/load

수집기가 수집한 상품의 옵션과 재고를 적재한다. 쓰기 전용이며 `/internal` 아래 둔다.

요청

{
  "productId": 101,
  "options": [
    { "optionKey": "100ml", "name": "토너 100ml", "price": 15000, "quantity": 30 },
    { "optionKey": "200ml", "name": "토너 200ml", "price": 25000, "quantity": 20 }
  ]
}

응답

{ "productId": 101, "inserted": 2, "updated": 0 }

- 같은 요청을 여러 번 보내도 재고가 변하지 않는다(멱등).
- 새 옵션은 재고까지 넣는다. 이미 있는 옵션은 이름·가격만 갱신하고 재고는 건드리지 않는다.
- 옵션은 `(productId, optionKey)`로 구분한다.
- `quantity`는 0 이상 정수다. 음수면 400을 반환한다.
- 한 요청의 옵션은 최대 50개다.
- 이 API로 적재한 재고는 기존 `POST /api/v1/inventories/check`가 상품 단위로 합산해 응답한다.

| status | 의미 |
|---|---|
| inserted | 새로 넣은 옵션 수 |
| updated | 이름·가격만 갱신한 옵션 수 |

오류

{ "code": "INVALID_INVENTORY_LOAD", "message": "요청 형식이 올바르지 않습니다." }

### 주문 생성

```text
POST /api/v1/orders
```

옵션과 수량을 받아 재고 확인·차감·주문 생성을 한 트랜잭션으로 처리한다.

요청

```json
{
  "ordererKey": "demo",
  "items": [
    { "productId": 101, "optionKey": "11", "quantity": 2 },
    { "productId": 102, "optionKey": "31", "quantity": 1 }
  ]
}
```

응답 (201)

```json
{
  "orderId": 1,
  "totalPrice": 51800,
  "items": [
    { "productId": 101, "optionKey": "11", "name": "수분크림 A 50ml", "unitPrice": 12900, "quantity": 2 },
    { "productId": 102, "optionKey": "31", "name": "쿠션 B 21호", "unitPrice": 26000, "quantity": 1 }
  ]
}
```

- 항목 하나라도 실패하면 주문 전체가 실패하고, 앞서 차감한 재고도 모두 되돌린다.
- 같은 옵션이 여러 번 들어오면 수량을 합쳐 한 항목으로 처리한다.
- `unitPrice`는 주문 시점의 옵션 가격을 복사해 저장한다. 이후 가격이 바뀌어도 주문 내역은 바뀌지 않는다.
- `quantity`는 1~99 정수다. 한 요청의 항목은 최대 20개다.
- `ordererKey`, `optionKey`는 100자 이하다. 범위를 벗어나면 400을 반환한다.
- 시연 단계에서 `ordererKey`는 고정값 `"demo"`를 쓴다.
- 취소·환불은 없다. 시연용 재고는 별도 리셋 수단으로 되돌린다.

실패 응답

공통 오류 본문에 `failedItem`을 더한다. agent가 실패 사유와 원래 조건을 보고 대안 상품을 다시 찾을 수 있게 한다.

```json
{
  "code": "INSUFFICIENT_STOCK",
  "message": "주문할 수 없는 항목이 있습니다.",
  "failedItem": { "productId": 101, "optionKey": "11", "requested": 5, "available": 2 }
}
```

| code | HTTP | 의미 |
|---|---|---|
| `OUT_OF_STOCK` | 409 | 재고 0개 |
| `INSUFFICIENT_STOCK` | 409 | 재고는 있지만 요청 수량보다 적음 |
| `OPTION_NOT_FOUND` | 404 | `(productId, optionKey)`에 해당하는 옵션이 없음 |
| `INVALID_ORDER` | 400 | 요청 형식 오류 (`failedItem` 없음) |
| `CONCURRENT_UPDATE` | 409 | 재고는 남아 있지만 다른 주문이 먼저 변경함 (낙관적 락). 다시 시도하면 성공할 수 있음 |
| `LOCK_TIMEOUT` | 503 | 락 대기 시간 안에 락을 얻지 못함 (Redisson). 재고를 확인하기 전이라 `available`은 의미가 없다(0) |
| `LOCK_UNAVAILABLE` | 503 | Redis에 연결하지 못해 주문을 받지 않음 (Redisson). 재고를 확인하기 전이라 `available`은 의미가 없다(0) |

## 4. 화면 표시 규칙

agent는 `NOT_FOUND` 상품을 응답에서 제외한다. 화면이 다루는 상태는 세 가지다.

| status | 화면 표시 |
|---|---|
| `IN_STOCK` | 재고 N개 · 내일 도착 |
| `OUT_OF_STOCK` | 품절 |
| `UNKNOWN` | 재고 확인 불가 |

`reason`이 `null`이면 그 줄을 숨기고 `evidence`만 보여준다. 1C 전까지는 계속 `null`이다.

목업 응답은 [mocks/chat-response.example.json](mocks/chat-response.example.json)에 있다. 백엔드 없이 이 파일만으로 화면을 만들 수 있다.

## 5. 완료 기준

Inventory API (order-service)

- 재고 있는 상품, 품절 상품, 존재하지 않는 상품 ID 세 개를 한 번에 요청하면 결과가 정확히 3개 돌아온다.
- 세 결과의 `status`가 각각 `IN_STOCK`, `OUT_OF_STOCK`, `NOT_FOUND`다.
- `NOT_FOUND`인 결과의 `quantity`와 `estimatedDeliveryDate`가 `null`이다.
- 21개를 요청하면 400과 오류 본문을 반환한다.

Order API (order-service)

- 재고가 충분하면 재고가 요청 수량만큼 줄고, 주문 항목의 `unitPrice`가 주문 시점 가격과 같다.
- 두 항목 중 하나라도 재고가 부족하면 409와 `failedItem`을 반환하고, 다른 항목의 재고도 줄지 않는다.
- 재고 5개인 옵션에 10명이 동시에 1개씩 주문하면 정확히 5건만 성공하고 재고는 0이 된다.

Catalog API (catalog-service)

- `q`가 상품명에만 있는 상품과 리뷰 본문에만 있는 상품이 모두 결과에 들어온다.
- `maxPrice`를 넘는 상품이 결과에 없다.
- 결과의 모든 상품이 `evidence`를 1개 이상 가진다.
- `limit`보다 많은 상품을 반환하지 않는다.

Agent API (agent-service)

- catalog와 order가 모두 정상일 때 상품 카드에 `evidence`와 `inventory`가 채워진다.
- order-service를 내린 뒤 같은 질문을 하면 카드가 그대로 나오고 `inventory.status`가 전부 `UNKNOWN`이다.
- catalog-service를 내린 뒤 같은 질문을 하면 오류 본문을 반환한다.
