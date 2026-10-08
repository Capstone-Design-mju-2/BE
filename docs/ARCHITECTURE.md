# 아키텍처

## 현재 구현 — Stage 1B

agent-service가 시작할 때 `search-mcp`와 `inventory-mcp`를 자식 프로세스로 띄워 stdio 세션을 재사용한다(ADR-67, ADR-68). 세션이 끊기거나 호출이 제한 시간 안에 끝나지 않으면 세션을 다시 열고 한 번 재시도한다(ADR-69).

```text
agent-service
  ├─ search-mcp    → catalog-service → catalog DB
  └─ inventory-mcp → order-service   → order DB
```

`POST /api/v1/chat`은 검색 결과의 `productId`로 재고를 확인해 카드를 만든다. `answer`는 고정 템플릿이고 `reason`은 `null`이다. 1C(LLM 도구 선택)는 아직 구현하지 않았다.

데이터는 수집 스크립트가 만든 JSONL을 적재 스크립트가 서비스의 적재 API로 넣는다. 서비스를 거치지 않고 DB에 직접 쓰지 않는다.

```text
scripts/collect_musinsa.py → JSONL (.local/, 저장소 밖)
scripts/load_catalog.py    → catalog-service  POST /internal/products/load
scripts/seed_inventory.py  → order-service    POST /api/v1/internal/inventories/load
```

## 데이터 소유

| 구성요소 | 소유 데이터 | 성격 |
|---|---|---|
| catalog-service | 상품·리뷰 | 원천 |
| order-service | 주문·재고 | 원천 |
| agent-service | 없음 | 오케스트레이션 |
| search-mcp | 없음 | 도구 인터페이스 |
| inventory-mcp | 없음 | 도구 인터페이스 |

## 단계별 확장

| 단계 | 추가할 것 | 먼저 확인할 문제 |
|---|---|---|
| 1 | 현재 골격과 수직 기능 | 질문에서 검색·재고 응답까지 연결 |
| 2 | RDB 검색과 부하 테스트 | 검색 지연과 실행 계획 |
| 3 | BGE-M3, OpenSearch, 인덱서 | 의미 검색 품질과 인덱스 불일치 |
| 4 | Outbox, Debezium, Kafka | 이중 쓰기 유실과 재처리 |
| 5 | DB 락, Redis Redisson | 동시 주문의 초과 판매 |
| 6 | Spring Cloud Gateway, 독립 배포 | 공통 정책과 서비스 간 실패 |

OpenSearch, Kafka, Debezium, Redis, Gateway는 해당 단계에 도달했을 때 추가한다. 현재부터 비활성 설정을 미리 넣지 않는다. 그래야 Git 이력에 문제와 해결 과정이 남는다.

## 문서 경계

- Notion ADR: 선택지, 결정, 근거, 포기한 것, 당시 몰랐던 것, 결과
- 저장소 문서: 현재 구현 구조, 실행 방법, 환경변수, 운영 명령
