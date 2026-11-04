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

- 검색은 `limit`만 쓴다. 목록 API(카테고리별 상품, 리뷰 조회)만 `page`·`size`로 나눠 준다.
- 대화 기록 식별자는 두지 않는다. 저장 여부가 미정이다. 품절 대안은 대화 기록 대신 앞 답의 검색 조건을 돌려받는다(1절 "품절 대안", ADR-131).

## 1. Agent API

```text
POST /api/v1/chat
```

요청

```json
{ "message": "건성 피부에 끈적이지 않는 수분크림 중 내일 도착 가능하고 3만원 이하인 상품 추천해 줘" }
```

`message`는 1자 이상 500자 이하다. 벗어나거나 없으면 400과 `{ "code": "INVALID_CHAT_REQUEST", "message": "..." }`를 반환한다.

`skinType`은 선택이다(FE 이슈 #10). `dry`, `oily`, `combination`, `sensitive` 중 하나이고, 주면 근거 리뷰를 고를 때 같은 피부 타입 리뷰를 먼저 고른다. 상품을 거르거나 순서를 바꾸지는 않는다. `null`은 주지 않은 것과 같고, 다른 값이면 400 `INVALID_CHAT_REQUEST`다. LLM이 정하지 않고 agent가 요청 값을 그대로 검색에 넘긴다. 검색 경로가 OpenSearch(`SEARCH_BACKEND=opensearch`)이면 인덱스에 피부 타입이 없어 반영되지 않는다.

```json
{ "message": "끈적이지 않는 수분크림 추천해 줘", "skinType": "dry" }
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
      "imageUrl": "https://image.msscdn.net/images/goods_img/20260101/101/101_1_500.jpg",
      "thumbnailUrl": "https://image.msscdn.net/images/goods_img/20260101/101/101_1_125.jpg",
      "reason": "건성 피부 사용자의 보습력 평가가 높고 끈적임 언급이 적습니다.",
      "evidence": [
        { "reviewId": 9001, "rating": 5, "excerpt": "건성인데 아침까지 당김 없이 촉촉해요", "skinType": "dry" },
        { "reviewId": 9037, "rating": 4, "excerpt": "바르고 나서 끈적임이 거의 없어요", "skinType": null }
      ],
      "inventory": {
        "status": "IN_STOCK",
        "quantity": 12,
        "estimatedDeliveryDate": "2026-09-17"
      }
    }
  ],
  "searchConditions": { "q": "수분크림", "max_price": 30000 }
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

`evidence` 항목마다 그 리뷰 작성자의 `skinType`을 붙인다. 작성자가 고르지 않은 리뷰는 `null`이고, 값은 리뷰 조회의 `skinType`과 같다. 검색 경로가 OpenSearch이면 이 필드가 없다.

`imageUrl`과 `thumbnailUrl`은 catalog 검색 응답 그대로다(2절). LLM에게 넘기는 검색 결과에서는 뺀다. 답에 쓰이지 않고 토큰만 늘기 때문이다. 검색 경로가 OpenSearch이면 두 필드가 없다.

`searchConditions`는 카드를 만든 검색의 조건이다. 키 이름은 검색 도구의 인자 그대로라 검색 경로마다 다르다(OpenSearch 경로에는 `product_types`가 더 있다). 피부 타입과 개수는 들어 있지 않다. 화면은 내용을 해석하지 않고 그 답과 함께 들고 있다가, 품절 대안을 요청할 때 그대로 돌려준다. 검색하지 않은 답은 `null`이다.

### 품절 대안

주문이 409 `OUT_OF_STOCK`으로 실패하면 화면은 "방금 품절됐어요"를 보이고, 같은 `POST /api/v1/chat`으로 처음 조건 그대로의 대안을 요청한다(ADR-131, PRD 스토리 8). 주문 화면의 옵션 조회에서 모든 옵션이 품절일 때도 같다.

요청

```json
{
  "message": "건성 피부에 끈적이지 않는 수분크림 중 내일 도착 가능하고 3만원 이하인 상품 추천해 줘",
  "skinType": "dry",
  "searchConditions": { "q": "수분크림", "max_price": 30000 },
  "excludeProductIds": [101]
}
```

- `message`와 `skinType`은 카드가 나온 처음 요청 그대로, `searchConditions`는 그 답의 값 그대로 보낸다.
- `excludeProductIds`에는 품절된 상품 ID를 넣는다. 주문 실패라면 `failedItem.productId`다. 대안에서 또 품절되면 앞서 뺀 ID에 더해 보낸다. 최대 10개다.
- agent는 LLM이 고른 검색 인자 대신 `searchConditions`로 검색하고, LLM은 답과 추천 이유만 쓴다. LLM이 막혀 규칙 답이 되어도 같은 조건으로 검색한다.
- `excludeProductIds`의 상품은 카드에 나오지 않는다. 뺀 만큼 더 찾아서 카드는 최대 5개다.
- 응답 모양은 위와 같고, `searchConditions`는 보낸 값 그대로다. 대안에 섞인 다른 품절 상품은 4절 규칙대로 "품절"로 보인다.
- 두 필드는 따로 써도 된다. `searchConditions`만 주면 조건만 고정하고, `excludeProductIds`만 주면 LLM이 조건을 다시 정한다.
- `excludeProductIds`가 숫자 배열이 아니거나 10개를 넘거나, `searchConditions`가 객체가 아니면 400 `INVALID_CHAT_REQUEST`다. 값을 바꿔 보내 검색 도구가 받지 않으면 502 `PRODUCT_SEARCH_FAILED`다.
- `INSUFFICIENT_STOCK`(재고가 요청 수량보다 적음)과 그 밖의 주문 실패는 품절 대안을 요청하지 않는다.

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
| `skinType` | X | `dry`, `oily`, `combination`, `sensitive`. 주면 근거를 고를 때 그 피부 타입 작성자의 리뷰를 먼저 고른다. 상품은 거르거나 순서를 바꾸지 않는다 |
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
      "imageUrl": "https://image.msscdn.net/images/goods_img/20260101/101/101_1_500.jpg",
      "thumbnailUrl": "https://image.msscdn.net/images/goods_img/20260101/101/101_1_125.jpg",
      "evidence": [
        { "reviewId": 9001, "rating": 5, "excerpt": "건성인데 아침까지 당김 없이 촉촉해요", "skinType": "dry" },
        { "reviewId": 9037, "rating": 4, "excerpt": "바르고 나서 끈적임이 거의 없어요", "skinType": null }
      ]
    }
  ]
}
```

- `evidence`는 상품당 최대 2개다. `q`가 리뷰 본문에 걸린 리뷰를 별점 높은 순으로 고르고, 동점이면 최신순으로 고른다. `q`가 상품명에만 걸려 리뷰 본문에 걸린 리뷰가 없는 상품은 같은 정렬로 그 상품의 전체 리뷰에서 고른다. 리뷰가 하나도 없는 상품은 결과에서 뺀다. 이 정렬 규칙은 잠정값이며 검색 품질 측정 후 바꿀 수 있다.
- `skinType`을 주면 위에서 고를 리뷰들(`q`가 걸린 리뷰, 없으면 전체 리뷰) 안에서 그 피부 타입 작성자의 리뷰를 먼저 고르고, 나머지는 같은 정렬을 따른다. `q`가 걸리지 않은 같은 피부 타입 리뷰를 `q`가 걸린 리뷰보다 앞에 두지는 않는다.
- `evidence`의 `skinType`은 작성자가 고른 값이고, 고르지 않았으면 `null`이다.
- `imageUrl`은 무신사 이미지 서버의 상품 사진(500px, 장당 약 190KB)이고 `thumbnailUrl`은 같은 사진의 125px(약 20KB)이다(ADR-127). 화면은 두 주소를 `srcset`으로 함께 주어 브라우저가 사진 칸 크기와 화면 배율에 맞는 것을 고르게 한다. 메인 카드(190px 이상)는 `imageUrl`을, 채팅 카드(96px)는 배율 1 화면에서만 `thumbnailUrl`을 받는다. 사진 파일은 우리 서버에 없고 브라우저가 무신사 서버(CDN, 1년 캐시)에서 바로 받는다.
- 사진 주소는 2026-11-02 무신사 상품 목록에서 받았다. 헬스/푸드(`104012`)는 무신사가 그 목록을 비우고 `104018`로 옮겨서 `104018` 목록에서 받았다. 그래도 없던 상품(품절 등)은 상품 상세 API로 채웠다. 상세 페이지에도 사진이 없는 39개만 둘 다 `null`이다(9,757개 중 9,718개에 사진이 있다). `thumbnailUrl`은 `imageUrl`의 이름 규칙(`_500`을 `_125`로)으로 만든 주소다. 화면은 한 크기를 못 불러오면 그 주소를 다시 받지 않고 남은 크기로 바꿔 쓴다.
- `excerpt`는 80자를 넘기지 않는다. LLM 입력 토큰은 이 값에 비례한다.
- `excerpt`는 `q`가 든 문장의 처음부터 보여준다. 문장은 줄바꿈이나 띄어쓰기가 뒤따르는 `.` `!` `?`에서 나눈다. 문장 처음부터 `q`까지가 80자를 넘으면 `q` 앞쪽 단어 처음부터 `…`를 붙여 보여준다.
- 피부 타입으로 상품을 거르지는 않는다. "건성"은 리뷰 본문 키워드로 걸린다. 채팅의 `skinType`은 이 API의 `skinType`으로 넘어가 근거 리뷰를 고르는 순서에만 쓴다.
- `category`와 `brand`는 질문에서 LLM이 도구 인자로 채운다.
- `excludeIngredient`는 성분표의 성분 이름과 정확히 같아야 한다. LLM은 MCP 도구에서 향료·알코올·미네랄오일 중에 고르고, search-mcp가 실제 성분 이름(알코올이면 에탄올·변성알코올·알코올·아이소프로필알코올)으로 바꿔 보낸다.

### 카테고리별 상품 목록

```text
GET /api/v1/products?category=104001&sort=popular&page=0&size=20
```

메인 화면의 카테고리 목록과 랭킹이 부른다.

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `category` | O | 카테고리 코드 6자리 |
| `sort` | X | `popular`(리뷰 수 많은 순, 기본), `rating`(평점 높은 순), `priceAsc`, `priceDesc` |
| `page` | X | 0부터 센다. 기본 0 |
| `size` | X | 기본 20, 최대 50 |

응답

```json
{
  "category": "104001",
  "page": 0,
  "size": 20,
  "total": 2185,
  "products": [
    { "productId": 101, "name": "수분크림 A", "brand": "브랜드 A", "price": 25900, "reviewCount": 1520, "reviewScore": 96,
      "imageUrl": "https://image.msscdn.net/images/goods_img/20260101/101/101_1_500.jpg",
      "thumbnailUrl": "https://image.msscdn.net/images/goods_img/20260101/101/101_1_125.jpg" }
  ]
}
```

- 메인 화면 랭킹은 `sort=popular`로 부른다.
- 정렬 값이 같으면 `productId` 순으로 이어 정렬해서 페이지끼리 겹치지 않는다. `page`가 마지막 쪽을 넘으면 `products`는 빈 배열이고 `total`은 그대로다.
- `imageUrl`, `thumbnailUrl`은 검색 응답과 같다(위 검색의 사진 규칙).
- `reviewScore`는 수집한 평점 그대로 0~100이다.
- 상품 이미지는 수집하지 않아 응답에 없다.
- 없는 카테고리 코드(상품이 하나도 없는 코드)나 범위를 벗어난 `page`·`size`·`sort`는 400 `INVALID_PRODUCT_LIST`다.

### 리뷰 조회

```text
GET /api/v1/products/{productId}/reviews?sort=recent&skinType=dry&page=0&size=20
```

상품 하나의 리뷰를 나눠 준다.

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `sort` | X | `recent`(최신순, 기본), `rating`(별점 높은 순), `likes`(좋아요 많은 순) |
| `skinType` | X | `dry`, `oily`, `combination`, `sensitive`. 주면 그 피부 타입 작성자의 리뷰만 준다 |
| `page` | X | 0부터 센다. 기본 0 |
| `size` | X | 기본 20, 최대 50 |

응답

```json
{
  "productId": 101,
  "page": 0,
  "size": 20,
  "total": 285,
  "reviews": [
    { "reviewId": 9001, "rating": 5, "content": "건성인데 아침까지 당김 없이 촉촉해요", "skinType": "dry", "optionText": "50ml", "likeCount": 3, "writtenAt": "2026-08-01" }
  ]
}
```

- 리뷰 본문은 자르지 않고 준다.
- 정렬 값이 같으면 최신순, 그다음 `reviewId` 큰 순으로 이어 정렬해서 페이지끼리 겹치지 않는다. `page`가 마지막 쪽을 넘으면 `reviews`는 빈 배열이다.
- `total`은 수집해 둔 리뷰 수다. 리뷰는 상품마다 최대 300개까지만 수집해 두어서, 상품 목록의 `reviewCount`(수집 당시 무신사의 전체 리뷰 수)보다 작을 수 있다.
- `writtenAt`은 작성 시각의 한국 시간 날짜다.
- `optionText`는 작성자가 산 옵션 이름이고, 옵션이 없으면 `null`이다.
- `skinType`은 작성자가 고른 값이고, 고르지 않았으면 `null`이다(지금 데이터에서 리뷰의 32.5%). 드물게 `dehydrated_oily`, `normal`, `trouble_prone`도 온다(합쳐 0.1%).
- 작성자 키·몸무게 구간과 성별은 주지 않는다.
- 없는 상품은 404 `PRODUCT_NOT_FOUND`, 범위를 벗어난 파라미터는 400 `INVALID_REVIEW_LIST`다.

### 상품·리뷰 적재 (수집기 전용)

POST /internal/products/load

수집한 상품 한 개와 그 리뷰를 적재한다. 쓰기 전용이다. 구현 시점의 예외로 공통 규칙의 `/api/v1` 접두사를 따르지 않는다.

요청: `externalId`(무신사 상품번호), `name`, `brandName`, `categoryCode`, `normalPrice`, `price`, `reviewCount`, `reviewScore`, `collectedOn`, `reviews[]`. 리뷰는 `externalId`, `content`, `grade`, `likeCount`, `optionText`, `skinType`, `skinTone`, `gender`, 키·몸무게 구간, `writtenAt`, `survey`, `collectedOn`을 가진다.

응답: `{ "productId": 101, "reviewCount": 285 }`

- 상품은 `externalId`, 리뷰는 `(productId, externalId)`로 구분한다. 같은 요청을 여러 번 보내도 결과가 같다.
- 별점이 없는 리뷰(`grade` 0)는 DB 제약(1~5)에 걸리므로 보내는 쪽에서 뺀다(ADR-65).

### 상품 사진 주소 적재 (수집기 전용)

```text
PUT /internal/products/{externalId}/image
```

요청: `{ "imageUrl": "https://image.msscdn.net/..." }`. `scripts/load_thumbnails.py`가 부른다(ADR-127).

- 성공하면 204, 그 무신사 상품번호의 상품이 없으면 404다.
- `imageUrl`은 `https://`로 시작하는 300자 이하 주소만 받는다. 화면이 `img` 태그에 그대로 넣기 때문이다. 아니면 400이다.
- 상품·리뷰를 다시 적재해도 사진 주소는 지워지지 않는다.

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

### 옵션 조회

```text
GET /api/v1/inventories/{productId}/options
```

주문 화면이 옵션을 고를 때 부른다. 아직 구현 전이다(10주차, 이슈 #28).

응답 (200)

```json
{
  "productId": 101,
  "options": [
    { "optionKey": "11", "name": "수분크림 A 50ml",     "price": 12900, "quantity": 12, "status": "IN_STOCK" },
    { "optionKey": "12", "name": "수분크림 A 50ml 2개", "price": 23900, "quantity": 0,  "status": "OUT_OF_STOCK" }
  ]
}
```

- `price`는 그 옵션으로 주문할 때 `unitPrice`에 복사되는 값이다. 주문 화면은 이 가격을 보여 준다. 채팅 카드의 `price`는 상품 대표 가격이라 옵션 가격과 다를 수 있다.
- `status`는 `quantity`가 1 이상이면 `IN_STOCK`, 0이면 `OUT_OF_STOCK`이다.
- 옵션은 `optionKey` 순서로 준다.
- 경로를 `/api/v1/inventories` 아래에 두어, 서비스마다 경로 앞부분이 겹치지 않는다(catalog는 `/api/v1/products`).

order DB에 옵션이 하나도 없는 상품은 404를 반환한다.

```json
{ "code": "PRODUCT_NOT_FOUND", "message": "옵션 정보가 없는 상품입니다." }
```

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
  "requestId": "5f0c6a3e-8b1d-4e2a-9c7f-3d2b1a0e9f84",
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
- `ordererKey`, `optionKey`, `requestId`는 100자 이하다. 범위를 벗어나면 400을 반환한다.
- 시연 단계에서 `ordererKey`는 고정값 `"demo"`를 쓴다.
- 취소·환불은 없다. 시연용 재고는 `make reset-inventory CONFIRM=1`로 재고 테이블을 비운 뒤 다시 적재해 되돌린다.

같은 주문을 다시 보낼 때 (`requestId`, 아직 구현 전이다. 10주차, 이슈 #28)

- `requestId`는 선택이다. 주문 시도 하나마다 새로 만든 값(UUID 등)을 보낸다.
- 같은 `requestId`로 다시 오면 재고를 다시 줄이지 않고, 처음 만든 주문을 201과 같은 본문으로 돌려준다. 응답이 끊겨 결과를 모를 때는 같은 `requestId`로 다시 보내면 된다.
- 같은 `requestId`가 동시에 두 번 와도 주문은 하나만 생긴다(`orders.request_id` 고유 제약).
- 실패 응답은 기록하지 않는다. 실패한 주문의 `requestId`로 다시 보내면 그 시점의 재고로 다시 시도한다.
- 같은 `requestId`에 다른 항목을 보내도 처음 주문을 돌려준다. 항목이 같은지는 비교하지 않는다.

실패 응답

공통 오류 본문에 `failedItem`을 더한다. `OUT_OF_STOCK`이면 화면이 `failedItem.productId`를 빼고 품절 대안을 요청한다(1절 "품절 대안").

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

상품 사진은 `imageUrl`과 `thumbnailUrl`을 `srcset`으로 함께 주어 브라우저가 사진 칸 크기와 화면 배율에 맞는 것을 고르게 한다. `loading="lazy"`로 화면에 가까워질 때만 받고, 사진 자리의 가로·세로를 미리 정해 카드가 밀리지 않게 한다. 두 필드가 `null`이면 "이미지 없음"을 보인다. 한 크기를 못 불러오면 남은 크기로 바꾸고, 둘 다 못 불러오면 "이미지 없음"을 보인다(ADR-127).

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
- 카테고리별 상품 목록을 같은 정렬로 0쪽과 1쪽 받으면 겹치는 상품이 없다.
- 리뷰 조회에 `skinType`을 주면 그 피부 타입 작성자의 리뷰만 돌아오고, 없는 상품은 404다.
- 검색에 `skinType`을 주면 상품 목록과 순서는 그대로이고, 상품마다 `q`가 걸린 리뷰 중 그 피부 타입 작성자의 리뷰가 근거 앞에 온다.
- 사진 주소가 있는 상품은 목록과 검색에 `imageUrl`과 `thumbnailUrl`이 오고, 없는 상품은 둘 다 `null`이다.

Agent API (agent-service)

- catalog와 order가 모두 정상일 때 상품 카드에 `evidence`와 `inventory`가 채워진다.
- order-service를 내린 뒤 같은 질문을 하면 카드가 그대로 나오고 `inventory.status`가 전부 `UNKNOWN`이다.
- catalog-service를 내린 뒤 같은 질문을 하면 오류 본문을 반환한다.
- `skinType`을 주면 LLM이 무엇을 넣든 그 값이 검색에 넘어가고, 네 값 밖이면 400 `INVALID_CHAT_REQUEST`다.
- 카드에는 사진 주소가 오고, LLM에게 넘기는 검색 결과에는 사진 주소가 없다.
- 검색한 답에는 `searchConditions`가 있다.
- `searchConditions`를 주면 LLM이 무엇을 넣든 그 값으로 검색하고, 응답의 `searchConditions`가 보낸 값과 같다. LLM 없이 규칙으로 답해도 같다.
- `excludeProductIds`의 상품은 카드에 없고, 카드는 최대 5개다.
