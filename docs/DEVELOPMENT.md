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
| opensearch | 9200 |

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

MCP 서버는 stdio transport를 사용한다. agent-service가 시작할 때 `search-mcp`와 `inventory-mcp`를 자식 프로세스로 띄우고 세션을 재사용하므로(ADR-67, ADR-68) `/chat`을 쓰는 데는 따로 실행할 필요가 없다. 서버 프로세스가 죽으면 다음 호출이 세션을 다시 열고 한 번 재시도한다(ADR-69). 호출이 35초 안에 끝나지 않아도 같은 방식으로 세션을 다시 연다(도구가 catalog·order를 부르는 HTTP 제한 30초보다 커야 느리지만 정상인 서버를 재시작하지 않는다). 질문 하나의 LLM 호출 전체는 `LLM_TIMEOUT_SECONDS`(기본 60초) 안에 끝나야 하고, 넘으면 LLM 없는 규칙 방식으로 답한다. 도구만 단독으로 확인하려면 다음처럼 실행한다.

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
uv run python scripts/collect_options.py .local/musinsa/104001-*.jsonl  # 상품 옵션(SKU) 목록
uv run python scripts/load_catalog.py .local/musinsa/104001-*.jsonl     # catalog-service가 떠 있어야 한다
uv run python scripts/seed_inventory.py .local/musinsa/104001-*.jsonl   # catalog-service와 order-service가 떠 있어야 한다
uv run python scripts/collect_essentials.py .local/musinsa/full/*.jsonl  # 상품 고시 정보(성분표)
uv run python scripts/load_ingredients.py .local/musinsa/essentials/essentials*.jsonl \
    --glowpick .local/musinsa/essentials/glowpick.jsonl  # catalog-service가 떠 있어야 한다
```

적재 스크립트는 같은 파일을 다시 넣어도 결과가 같다. `load_catalog.py`는 별점이 없는 리뷰(`grade` 0)를 건너뛴다. `seed_inventory.py`는 무신사 옵션(SKU)마다 재고 1행을 만든다. 수량은 그 옵션을 적은 리뷰 수로 정하고(0개는 품절, 50 미만 3개, 50~999개 10개, 1000개 이상 30개), 두 개를 고르는 세트 상품은 두 값 중 리뷰가 적은 쪽으로, 옵션이 없는 상품은 상품 리뷰 수로 정한다. 이미 있는 재고의 수량은 바꾸지 않으므로 규칙을 바꿔 다시 넣으려면 먼저 `make reset-inventory CONFIRM=1`로 재고 테이블을 비운다. 주문으로 바뀐 수량도 함께 지워진다. `productId`를 얻으려고 상품을 catalog에 다시 보내므로 파일이 크면 리뷰를 다시 쓰는 시간이 든다. `load_ingredients.py`는 성분표를 성분 이름으로 나눠 상품마다 목록을 통째로 바꾼다. "상세페이지 참조"처럼 목록이 아니거나 띄어쓰기로만 나뉜 성분표는 빈 목록으로 보내 성분 정보가 없는 상품으로 남긴다. 무신사 성분표가 "상세페이지 참조"인 상품은 글로우픽에서 찾은 성분(`glowpick.jsonl`, 용량이 같은 매칭만)으로 채우고 출처를 함께 저장한다. 글로우픽 수집 스크립트는 저장소에 두지 않으므로 `glowpick.jsonl`은 따로 전달받는다. 없으면 `--glowpick`을 빼고 무신사 성분표만 적재한다.

### 의미 검색 (OpenSearch)

`SEARCH_BACKEND=opensearch`이면 search-mcp가 질문을 BGE-M3로 임베딩해 OpenSearch의 리뷰 벡터를 찾는다(ADR-101, ADR-102). 기본값 `catalog`는 지금까지처럼 catalog-service의 단어 검색을 쓴다. 모델과 torch는 search-mcp의 선택 의존성이라 따로 설치한다. `make bootstrap`처럼 `--inexact` 없이 `uv sync`를 하면 지워진다.

```bash
uv sync --locked --all-packages --all-extras
docker compose up -d --wait opensearch
caffeinate -i uv run --package search-mcp --extra embed python scripts/embed_reviews.py  # 리뷰 80만 개, M2 GPU로 약 6시간
uv run --package search-mcp --extra embed python scripts/index_reviews.py
```

`embed_reviews.py`는 벡터를 `.local/embeddings/`에 1만 개씩 저장하고, 멈췄다 다시 실행하면 끝난 묶음을 건너뛴다. `index_reviews.py`는 같은 이름의 인덱스를 지우고 다시 만든다. 리뷰 문서마다 상품명·브랜드·가격·카테고리·성분을 복사해 넣으므로, 색인한 뒤 catalog에서 바뀐 상품 정보는 다시 색인할 때까지 반영되지 않는다. 이 어긋남은 `uv run --package search-mcp --extra embed python scripts/repro_index_mismatch.py`로 재현한다. 검색 1위 상품의 catalog 가격을 잠시 올렸다가 끝나면 되돌린다. search-mcp는 시작할 때 모델을 읽어 들이는 데 약 10초가 걸린다. 스모크 테스트는 모델 없이 `scripts/fixtures/`의 지어낸 리뷰와 미리 계산한 질문 벡터로 OpenSearch 경로를 확인한다. 픽스처는 `scripts/make_search_fixture.py`로 다시 만든다.

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
