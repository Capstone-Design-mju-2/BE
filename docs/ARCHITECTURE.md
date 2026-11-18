# 아키텍처

## 현재 구현

화면의 요청은 Caddy와 gateway-service를 거쳐 서비스로 간다(ADR-133). agent-service는 시작할 때 `search-mcp`와 `inventory-mcp`를 자식 프로세스로 띄워 stdio 세션을 재사용한다(ADR-67, ADR-68). 세션이 끊기거나 호출이 제한 시간 안에 끝나지 않으면 세션을 다시 열고 한 번 재시도한다(ADR-69).

```text
화면 → Caddy → gateway-service
                 ├─ /api/v1/chat          → agent-service ─ LLM
                 │                            ├─ search-mcp    → OpenSearch(리뷰 벡터) + catalog-service(사진, 구매자 설문)
                 │                            └─ inventory-mcp → order-service
                 ├─ /api/v1/products...   → catalog-service → catalog DB
                 └─ /api/v1/orders...,
                    /api/v1/inventories... → order-service  → order DB, Redis
```

`POST /api/v1/chat`에서 LLM이 도구를 고른다. `search_products`로 리뷰가 질문과 뜻이 맞는 상품을 찾고, 근거 리뷰가 질문 조건을 말하지 않으면 `search_product_reviews`로 그 상품의 리뷰에서 다시 찾고(ADR-136), `check_inventory`로 재고를 확인한 뒤 답과 추천 이유를 쓴다. 상품 유형을 여럿 묻는 질문은 하위 에이전트가 유형별로 나눠 찾는다(ADR-138).

검색(`SEARCH_BACKEND`)은 세 가지다. 로컬 기본값은 `catalog`이고 시연 서버는 `opensearch`다.

| 값 | 찾는 방법 |
|---|---|
| `catalog` | catalog DB에서 상품명과 리뷰 본문의 단어 검색 |
| `opensearch` | 질문을 BGE-M3로 임베딩해 OpenSearch의 리뷰 벡터 검색(ADR-101, ADR-102) |
| `hybrid` | 리뷰 벡터 검색과 리뷰 본문 키워드 검색의 순위를 합침(ADR-174). 측정에서 효과가 작아 기본 경로가 아니다 |

OpenSearch 경로에서는 찾은 상품 20개를 무신사 구매자 설문의 응답 비율로 다시 줄 세워 5개를 고른다(ADR-177). 검색은 조건을 말하는 리뷰가 있는 상품을 찾고, 그 조건이 대체로 맞는지는 설문이 안다.

가격이 바뀌면 catalog-service가 같은 트랜잭션에 `outbox` 행을 남기고 indexer가 읽어 OpenSearch에 반영한다(ADR-121). Debezium·Kafka로 옮기는 경로는 로컬에서 같은 조건으로 비교했고 서버에는 올리지 않았다(ADR-132). 시연 서버의 가격은 바뀌지 않아 indexer도 서버에는 없다.

데이터는 수집 스크립트가 만든 JSONL을 적재 스크립트가 서비스의 적재 API로 넣는다. 서비스를 거치지 않고 DB에 직접 쓰지 않는다. 로컬 초기화용 make 타깃(`infra-reset`, `reset-inventory`)만 예외다.

```text
scripts/collect_musinsa.py → JSONL (.local/, 저장소 밖)
scripts/collect_options.py → JSONL (.local/, 저장소 밖)
scripts/load_catalog.py    → catalog-service  POST /internal/products/load
scripts/seed_inventory.py  → order-service    POST /api/v1/internal/inventories/load
```

## 데이터 소유

| 구성요소 | 소유 데이터 | 성격 |
|---|---|---|
| catalog-service | 상품·리뷰 | 원천 |
| order-service | 주문·재고 | 원천 |
| OpenSearch | 리뷰 벡터와 리뷰 본문(상품 필드 복사본 포함) | catalog에서 만든 사본 |
| agent-service | 없음 | 오케스트레이션 |
| gateway-service | 없음 | 경로 모음 |
| search-mcp | 없음 | 도구 인터페이스 |
| inventory-mcp | 없음 | 도구 인터페이스 |

## 단계별 확장

| 단계 | 추가한 것 | 먼저 확인한 문제 |
|---|---|---|
| 1 | 현재 골격과 수직 기능 | 질문에서 검색·재고 응답까지 연결 |
| 2 | RDB 검색과 부하 테스트 | 검색 지연과 실행 계획 |
| 3 | BGE-M3, OpenSearch, 인덱서 | 의미 검색 품질과 인덱스 불일치 |
| 4 | Outbox, Debezium, Kafka | 이중 쓰기 유실과 재처리 |
| 5 | DB 락, Redis Redisson | 동시 주문의 초과 판매 |
| 6 | Spring Cloud Gateway, 독립 배포 | 공통 정책과 서비스 간 실패 |

OpenSearch, Kafka, Debezium, Redis, Gateway는 해당 단계에 도달했을 때 추가했다. 비활성 설정을 미리 넣지 않아서 Git 이력과 태그(`v0.1-vertical-slice`부터 `v1.0-final`)에 문제와 해결 과정이 남아 있다. 여섯 단계는 모두 끝났다.

## 문서 경계

- Notion ADR: 선택지, 결정, 근거, 포기한 것, 당시 몰랐던 것, 결과
- 저장소 문서: 현재 구현 구조, 실행 방법, 환경변수, 운영 명령
