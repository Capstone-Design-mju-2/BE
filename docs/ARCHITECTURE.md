# 아키텍처

## 현재 구현 — Stage 0 골격

각 프로세스의 기동 경계와 독립 DB 연결만 구현되어 있다. 화살표가 없는 구성요소끼리는 아직 호출하지 않는다.

```text
[agent-service: health/config]
[search-mcp: health tool]
[inventory-mcp: health tool]

[catalog-service] → [catalog DB]
[order-service]   → [order DB]
```

상품, 리뷰, 주문, 재고 도메인과 agent→MCP→Spring 연결은 아직 구현하지 않는다.

## Stage 1 목표 — 수직 기능

```text
agent-service
  ├─ search-mcp    → catalog-service → catalog DB
  └─ inventory-mcp → order-service   → order DB
```

이 연결은 질문 입력에서 상품 검색과 재고 응답까지 이어지는 첫 시연 버전에서 구현한다.

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
