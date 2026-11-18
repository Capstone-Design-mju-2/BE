# Capstone Design MJU 2 — Backend

자연어 질문에서 상품 검색 결과와 실시간 재고를 조합하는 Agentic RAG 커머스 서비스의 백엔드 모노레포다.

이 저장소는 최소 구조를 먼저 동작시킨 뒤 OpenSearch, Outbox, Debezium, Kafka, Redis, Gateway를 단계적으로 추가했다. 각 단계는 같은 시나리오로 도입 전후를 측정하고 ADR에 결과를 남겼다.

## 현재 단계

계획한 단계를 모두 구현했다(11/18 기준). 사용자가 질문하면 agent-service의 LLM이 `search-mcp`와 `inventory-mcp`의 도구를 골라 부르고, 리뷰를 근거로 고른 상품 카드에 재고와 도착일을 붙여 답한다(`POST /api/v1/chat`). 카드에서 바로 주문할 수 있고, 그사이 품절되면 같은 조건으로 대안을 다시 찾는다.

| 단계 | 한 일 | 측정 결과 |
|---|---|---|
| 직접 호출에서 MCP로 | agent가 catalog와 order를 REST로 부르던 것을 MCP 도구 호출로 바꿈 | 같은 질문에 같은 응답 |
| LLM 도구 선택 | LLM이 도구와 인자를 고르고 답과 추천 이유를 씀(Claude 하이쿠) | 하이쿠와 소넷을 같은 질문으로 비교해 고름 |
| RDB 검색 | 리뷰 80만 건 단어 검색의 쿼리 모양을 바꿈 | 검색 p95 2,419ms에서 453ms |
| 의미 검색 | 리뷰 801,690개를 BGE-M3로 임베딩해 OpenSearch에서 뜻으로 찾음 | 동시 요청 10개 p95 5,914ms에서 411ms |
| 인덱스 동기화 | 이중 쓰기를 Outbox로 바꾸고, Debezium·Kafka와 비교 | 장애 10초 동안 잃은 가격 변경 50건에서 0건(Outbox). Kafka는 로컬 비교 실험 |
| 재고 동시성 | 조건부 차감, 비관적·낙관적 락, Redisson | 재고 50개에 주문 200건, 초과 판매 150건에서 0건 |
| Gateway | Spring Cloud Gateway로 경로를 하나로 모음 | 주문 서비스가 멈추면 15초 무응답에서 10초 뒤 503 |
| 에이전트 | 근거가 조건을 말하지 않으면 그 상품 리뷰에서 다시 찾기, 상품 유형이 여럿이면 나눠 찾기, 품절 대안 | 복합 질문 24번 중 물은 유형을 모두 담은 답 0번에서 24번 |
| 추천 순위 | 검색으로 찾은 상품 20개를 무신사 구매자 설문의 응답 비율로 다시 줄 세움 | 설문으로 정답을 계산하는 질문 234개의 정밀도@5 42.6%에서 59.2%, 기존 질문 21개는 81.9%에서 82.9% |

- 추천 품질은 추천 5개 중 정답 상품의 비율(정밀도@5)로 본다. 질문과 채점 코드는 `eval/`에 있다.
- 하이브리드 검색(`SEARCH_BACKEND=hybrid`)과 Debezium·Kafka는 구현하고 측정했지만 기본 경로가 아니다. 하이브리드 검색은 효과가 작았고(+3.1%p), Kafka는 받는 쪽이 하나뿐인 지금 규모에서 Outbox 폴링과 유실이 같았다.
- 시연 서버 한 대에 Docker Compose로 올린다([배포 방법](docs/DEVELOPMENT.md)).

구성:

- Java 21 / Spring Boot 4.1.1: catalog-service, order-service, gateway-service
- Python 3.11 / uv workspace: agent-service, search-mcp, inventory-mcp, indexer
- PostgreSQL(catalog DB, order DB), OpenSearch, Redis, Kafka·Debezium(로컬 실험)
- Docker Compose

RDB는 PostgreSQL을 쓴다(ADR-124).

## 시작하기

필수 도구:

- Java 21
- Docker + Docker Compose
- uv

```bash
cp .env.example .env
make bootstrap
make check
make smoke
```

개별 서비스 실행:

```bash
make infra-up
make run-catalog       # http://127.0.0.1:8081/actuator/health
make run-order         # http://127.0.0.1:8082/actuator/health
make run-agent         # http://127.0.0.1:8000/health
make run-search-mcp    # stdio MCP server
make run-inventory-mcp # stdio MCP server
```

## 문서

- [개발환경과 실행 방법](docs/DEVELOPMENT.md)
- [현재 및 목표 아키텍처](docs/ARCHITECTURE.md)
- [API 계약](docs/API.md)
- [재고 동시성 측정](docs/CONCURRENCY.md)

설계 결정의 원본은 Notion의 캡디2 ADR에 둔다. 저장소 문서는 구현과 실행 방법을 설명한다.
