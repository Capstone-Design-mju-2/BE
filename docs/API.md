# API 계약 — Stage 1

구현보다 먼저 고정한 계약이다. Stage 1 동안 바꾸지 않는다. 결정 근거와 버린 선택지는 Notion ADR-19에 있다.

## 공통 규칙

- 모든 경로는 `/api/v1` 아래에 둔다.
- `productId`는 우리 DB의 숫자 ID다. 무신사 상품번호는 `externalId`로 따로 저장하고 응답에 노출하지 않는다. 재수집해도 화면 계약이 깨지지 않게 한다.
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
- 피부 타입 필터는 두지 않는다. "건성"은 리뷰 본문 키워드로 걸린다. 구조화 필터는 3단계 의미 검색과 비교한 뒤에 판단한다.

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
  "externalId": "musinsa-10294",
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

Catalog API (catalog-service)

- `q`가 상품명에만 있는 상품과 리뷰 본문에만 있는 상품이 모두 결과에 들어온다.
- `maxPrice`를 넘는 상품이 결과에 없다.
- 결과의 모든 상품이 `evidence`를 1개 이상 가진다.
- `limit`보다 많은 상품을 반환하지 않는다.

Agent API (agent-service)

- catalog와 order가 모두 정상일 때 상품 카드에 `evidence`와 `inventory`가 채워진다.
- order-service를 내린 뒤 같은 질문을 하면 카드가 그대로 나오고 `inventory.status`가 전부 `UNKNOWN`이다.
- catalog-service를 내린 뒤 같은 질문을 하면 오류 본문을 반환한다.
