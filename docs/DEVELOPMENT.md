# 개발환경

## 1. 버전

| 영역 | 버전 |
|---|---|
| Java | 21 |
| Spring Boot | 4.1.1 |
| Gradle Wrapper | 9.7.1 |
| Python | 3.11 |
| Python 패키지 관리자 | uv |
| PostgreSQL 이미지 | 17.6-alpine |

의존성 버전은 빌드 파일과 `uv.lock`으로 고정한다. Gradle 배포 파일은 공식 SHA-256으로 검증한다.

## 2. 최초 실행

```bash
cp .env.example .env
make bootstrap
make check
make smoke
```

`.env`는 로컬 전용이며 Git에 올리지 않는다. Make는 `.env`가 있으면 Compose, Spring, Python에 같은 값을 export한다. 기본 비밀번호는 loopback으로 제한된 로컬 개발에서만 사용한다.

## 3. 포트

모든 포트는 기본적으로 `127.0.0.1`에만 바인딩한다.

| 구성요소 | 포트 |
|---|---:|
| agent-service | 8000 |
| catalog-service | 8081 |
| order-service | 8082 |
| catalog-db | 5433 |
| order-db | 5434 |

## 4. 실행

DB를 먼저 실행한다.

```bash
make infra-up
```

각 서비스는 별도 터미널에서 실행한다.

```bash
make run-catalog
make run-order
make run-agent
```

MCP 서버는 stdio transport를 사용한다. agent-service가 시작할 때 `search-mcp`와 `inventory-mcp`를 자식 프로세스로 띄우고 세션을 재사용하므로(ADR-67, ADR-68) `/chat`을 쓰는 데는 따로 실행할 필요가 없다. 서버 프로세스가 죽으면 다음 호출이 세션을 다시 열고 한 번 재시도한다(ADR-69). 호출이 8초 안에 끝나지 않아도 같은 방식으로 세션을 다시 연다. 도구만 단독으로 확인하려면 다음처럼 실행한다.

```bash
make run-search-mcp
make run-inventory-mcp
```

Claude Desktop에 붙여 도구를 단독 시험하려면 `~/Library/Application Support/Claude/claude_desktop_config.json`에 다음을 추가하고 앱을 다시 시작한다. GUI 앱은 셸의 PATH를 받지 않으므로 `uv`가 아니라 `.venv/bin`의 절대 경로를 쓴다. catalog-service와 order-service가 떠 있어야 도구가 동작한다.

```json
{
  "mcpServers": {
    "search-mcp": {
      "command": "/절대/경로/BE/.venv/bin/search-mcp",
      "args": [],
      "env": { "CATALOG_SERVICE_URL": "http://127.0.0.1:8081" }
    },
    "inventory-mcp": {
      "command": "/절대/경로/BE/.venv/bin/inventory-mcp",
      "args": [],
      "env": { "ORDER_SERVICE_URL": "http://127.0.0.1:8082" }
    }
  }
}
```

수집과 적재는 스크립트로 한다. 수집한 JSONL은 `.local/` 아래에 두고 Git에 올리지 않는다.

```bash
uv run python scripts/collect_musinsa.py --category 104001 --products 25 --review-pages 3
uv run python scripts/load_catalog.py .local/musinsa/104001-*.jsonl     # catalog-service가 떠 있어야 한다
uv run python scripts/seed_inventory.py .local/musinsa/104001-*.jsonl   # catalog-service와 order-service가 떠 있어야 한다
```

적재 스크립트는 같은 파일을 다시 넣어도 결과가 같다. `load_catalog.py`는 별점이 없는 리뷰(`grade` 0)를 건너뛴다. `seed_inventory.py`는 상품마다 기본 옵션 1행의 재고를 만들고(리뷰 수 50 미만 3개, 50~999개 10개, 1000개 이상 30개) 이미 있는 재고의 수량은 바꾸지 않는다. `productId`를 얻으려고 상품을 catalog에 다시 보내므로 파일이 크면 리뷰를 다시 쓰는 시간이 든다.

## 5. 검증

정적 빌드와 잠금파일 검증:

```bash
make check
```

DB, Flyway, HTTP health, 실제 MCP stdio 호출까지 포함한 실행 검증:

```bash
make smoke
```

스모크는 프로세스와 컨테이너를 항상 정리하되 DB volume은 보존한다.

개발용 서비스가 8081, 8082, 8000에서 이미 떠 있으면 스모크는 옛 빌드를 검사하게 되므로 시작 전에 중단한다. 먼저 그 서비스를 내려야 한다. catalog-service와 order-service는 DB에 코드가 모르는 마이그레이션이 적용돼 있으면 기동을 거부한다(코드보다 앞선 스키마에 옛 빌드가 쓰기를 시도하는 사고를 막으려는 것이다).

## 6. 의존성 갱신

일반 설치는 `uv.lock`을 바꾸지 않는다. 의도적으로 Python 의존성을 갱신할 때만 다음을 실행하고 변경된 lock을 검토한다.

```bash
make dependencies-update
```

## 7. 데이터 초기화

다음 명령은 로컬 DB 볼륨을 삭제한다.

```bash
make infra-reset CONFIRM=1
```

## 8. 원칙

- 원천 DB는 서비스마다 물리적으로 분리한다.
- 다른 서비스의 DB를 직접 조회하지 않는다.
- 두 번째 구현이 생길 때 인터페이스를 추출한다.
- 새 기술을 추가하기 전에 기준선과 실패 재현 방법을 먼저 만든다.
- 현재 PostgreSQL 선택은 로컬 기본값이며 최종 RDB 결정은 ADR로 확정한다.
