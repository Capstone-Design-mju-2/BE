# Capstone Design MJU 2 — Backend

자연어 질문에서 상품 검색 결과와 실시간 재고를 조합하는 Agentic RAG 커머스 서비스의 백엔드 모노레포다.

이 저장소는 최소 구조를 먼저 동작시킨 뒤 OpenSearch, Outbox, Debezium, Kafka, Redis, Gateway를 단계적으로 추가한다. 각 단계는 같은 시나리오로 도입 전후를 측정하고 ADR에 결과를 남긴다.

## 현재 단계

Stage 0 개발환경과 독립 실행 가능한 서비스 골격만 포함한다. agent→MCP→Spring 연결과 도메인 기능은 Stage 1에서 구현한다.

- Java 21 / Spring Boot 4.1.1
- Python 3.11 / uv workspace
- catalog-service / catalog DB
- order-service / order DB
- agent-service
- search-mcp / inventory-mcp
- Docker Compose

PostgreSQL은 RDB 선택 ADR 전까지 사용하는 교체 가능한 로컬 기본값이다.

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

설계 결정의 원본은 Notion의 캡디2 ADR에 둔다. 저장소 문서는 구현과 실행 방법을 설명한다.
