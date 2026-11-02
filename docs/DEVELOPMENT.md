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

MCP 서버는 stdio transport를 사용한다. agent-service가 시작할 때 `search-mcp`와 `inventory-mcp`를 자식 프로세스로 띄우고 세션을 재사용하므로(ADR-67, ADR-68) `/chat`을 쓰는 데는 따로 실행할 필요가 없다. 서버 프로세스가 죽으면 다음 호출이 세션을 다시 열고 한 번 재시도한다(ADR-69). 호출이 35초 안에 끝나지 않아도 같은 방식으로 세션을 다시 연다(도구가 catalog·order·OpenSearch를 부르는 HTTP 제한 30초보다 커야 느리지만 정상인 서버를 재시작하지 않는다). 질문 하나의 LLM 호출 전체는 `LLM_TIMEOUT_SECONDS`(기본 60초) 안에 끝나야 하고, 넘으면 LLM 없는 규칙 방식으로 답한다. 도구만 단독으로 확인하려면 다음처럼 실행한다.

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
uv run python scripts/collect_thumbnails.py 104001 104002 104003 104005 104006 104007 104009 104010 104011 \
    104013 104014 104015 104016 104017 104018            # 상품 사진 주소, 요청 약 690번(약 15분)
uv run python scripts/load_thumbnails.py .local/musinsa/thumbnails.jsonl  # catalog-service가 떠 있어야 한다
```

적재 스크립트는 같은 파일을 다시 넣어도 결과가 같다. `load_catalog.py`는 별점이 없는 리뷰(`grade` 0)를 건너뛴다. `seed_inventory.py`는 무신사 옵션(SKU)마다 재고 1행을 만든다. 수량은 그 옵션을 적은 리뷰 수로 정하고(0개는 품절, 50 미만 3개, 50~999개 10개, 1000개 이상 30개), 두 개를 고르는 세트 상품은 두 값 중 리뷰가 적은 쪽으로, 옵션이 없는 상품은 상품 리뷰 수로 정한다. 이미 있는 재고의 수량은 바꾸지 않으므로 규칙을 바꿔 다시 넣으려면 먼저 `make reset-inventory CONFIRM=1`로 재고 테이블을 비운다. 주문으로 바뀐 수량도 함께 지워진다. `productId`를 얻으려고 상품을 catalog에 다시 보내므로 파일이 크면 리뷰를 다시 쓰는 시간이 든다. `load_ingredients.py`는 성분표를 성분 이름으로 나눠 상품마다 목록을 통째로 바꾼다. "상세페이지 참조"처럼 목록이 아니거나 띄어쓰기로만 나뉜 성분표는 빈 목록으로 보내 성분 정보가 없는 상품으로 남긴다. 무신사 성분표가 "상세페이지 참조"인 상품은 글로우픽에서 찾은 성분(`glowpick.jsonl`, 용량이 같은 매칭만)으로 채우고 출처를 함께 저장한다. 글로우픽 수집 스크립트는 저장소에 두지 않으므로 `glowpick.jsonl`은 따로 전달받는다. 없으면 `--glowpick`을 빼고 무신사 성분표만 적재한다. `collect_thumbnails.py`는 카테고리 목록을 끝까지 넘기며 상품 사진 주소만 받고 사진 파일은 받지 않는다(ADR-127). 목록에는 리뷰가 없는 상품까지 나와서 우리 카탈로그보다 훨씬 많다(11/02 27,076개). `load_thumbnails.py`는 상품마다 주소를 넣고 카탈로그에 없는 상품은 건너뛴다. 헬스/푸드(`104012`)는 11/02 무신사 목록이 비어 있고 일부가 건강식품(`104018`)으로 옮겨져서 명령에 `104018`을 넣었다. `104018`에도 없는 헬스/푸드 상품(11/02 650개)은 상품 상세 API(`goods-detail.musinsa.com/api2/goods/{상품번호}`)의 `thumbnailImageUrl`로 하나씩 받아 같은 형식으로 넣었다. 이 일회성 스크립트는 저장소에 두지 않았다.

### 의미 검색 (OpenSearch)

`SEARCH_BACKEND=opensearch`이면 search-mcp가 질문을 BGE-M3로 임베딩해 OpenSearch의 리뷰 벡터를 찾는다(ADR-101, ADR-102). 리뷰 100개를 가져와 상품별로 묶고, LLM이 상품 종류(`product_types`)를 주면 상품명에 그 말이 든 상품만 남긴다(ADR-115). 기본값 `catalog`는 지금까지처럼 catalog-service의 단어 검색을 쓴다. 모델과 torch는 search-mcp의 선택 의존성이라 따로 설치한다. `make bootstrap`처럼 `--inexact` 없이 `uv sync`를 하면 지워진다.

```bash
uv sync --locked --all-packages --all-extras
docker compose up -d --wait opensearch
caffeinate -i uv run --package search-mcp --extra embed python scripts/embed_reviews.py  # 리뷰 80만 개, M2 GPU로 약 6시간
uv run --package search-mcp --extra embed python scripts/index_reviews.py
```

`embed_reviews.py`는 벡터를 `.local/embeddings/`에 1만 개씩 저장하고, 멈췄다 다시 실행하면 끝난 묶음을 건너뛴다. `index_reviews.py`는 같은 이름의 인덱스를 지우고 다시 만든다. 리뷰 문서마다 상품명·브랜드·가격·카테고리·성분을 복사해 넣으므로, 색인한 뒤 catalog에서 바뀐 상품 정보는 다시 색인할 때까지 반영되지 않는다. 이 어긋남은 `uv run --package search-mcp --extra embed python scripts/repro_index_mismatch.py`로 재현한다. 검색 1위 상품의 catalog 가격을 잠시 올렸다가 끝나면 되돌린다. search-mcp는 시작할 때 모델을 읽어 들이는 데 약 10초가 걸린다. 스모크 테스트는 모델 없이 `scripts/fixtures/`의 지어낸 리뷰와 미리 계산한 질문 벡터로 OpenSearch 경로를 확인한다. 픽스처는 `scripts/make_search_fixture.py`로 다시 만든다.

### 검색 인덱스 동기화 실험 (이중 쓰기, Outbox)

catalog에서 바꾼 상품 가격을 리뷰 문서에 반영하는 두 방식을 비교한다(ADR-121). 실험용 가격 변경 API `PUT /internal/products/{id}/price`가 `CATALOG_INDEX_SYNC`에 따라 다르게 동작한다.

| 값 | 동작 |
|---|---|
| `none`(기본) | DB만 바꾼다 |
| `dual-write` | 커밋한 뒤 catalog-service가 OpenSearch를 직접 고친다. 실패하면 로그만 남는다 |
| `outbox` | 같은 트랜잭션에 `outbox` 행을 남기고, 인덱서(`make run-indexer`)가 1초마다 읽어 반영한다 |

```bash
CATALOG_INDEX_SYNC=outbox make run-catalog
uv run --package indexer python scripts/bench_index_sync.py outbox --pause-opensearch 5 10 --out .local/bench/index-sync/outbox-pause.json
```

`bench_index_sync.py`는 상품 100개의 가격을 0.2초 간격으로 바꾸고, 변경 요청부터 검색에 보이기까지 걸린 시간, 끝내 반영되지 않은 상품(유실), 두 번 이상 반영된 변경을 센다. 두 번 반영은 인덱서 기록과 함께, 상품마다 리뷰 문서 하나의 `_version` 증가분으로도 센다. 인덱서 기록은 응답을 받은 반영만 남기므로, 시간 초과된 요청이 서버에서 처리된 경우는 `_version`에만 잡힌다. `--pause-opensearch`는 OpenSearch 컨테이너를 잠시 멈추고(멈춘 동안 받은 요청이 풀린 뒤 처리될 수 있다), `--block-writes`는 리뷰 인덱스의 쓰기를 잠시 막고(그동안 쓰기는 403으로 실패한다), `--stop-indexer`는 인덱서를 잠시 내린다. outbox 모드에서는 스크립트가 인덱서를 직접 띄운다. 끝나면 같은 API로 가격을 되돌린다.

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
- RDB는 PostgreSQL로 확정했다(ADR-124).

## 9. 서버 배포 (시연 경로)

시연 경로(catalog·order·agent와 DB 두 개)를 서버 한 대에 Docker Compose로 올린다(ADR-123). 서버에는 Docker만 있으면 된다. 포트는 Caddy만 열고, Caddy가 경로별로 나눠 넘기며 팀 계정으로 막는다. `/internal/*`(적재·가격 변경 API)와 actuator는 밖에서 404다.

| 경로 | 서비스 |
|---|---|
| `/api/v1/chat` | agent-service |
| `/api/v1/products...` | catalog-service |
| `/api/v1/inventories...`, `/api/v1/orders...` | order-service |
| 그 밖의 GET | FE 빌드(서버 `/srv/peaupick-fe`) |

Caddy는 `SITE_ADDRESS` 이름으로 HTTPS를 받고, 그 이름의 인증서를 Let's Encrypt에서 스스로 받는다(ADR-126). 서버에서는 공인 IP의 점을 대시로 바꾸고 `.sslip.io`를 붙인 이름을 쓴다. IP로 들어오는 요청을 포함해 HTTP 요청은 이 HTTPS 주소로 넘긴다. 보안 그룹은 80번(인증서 발급과 넘기기)과 443번을 연다.

1. `deploy/.env.example`을 `deploy/.env`로 복사해 사이트 이름, DB 비밀번호, LLM 키, 팀 로그인 해시를 채운다. 해시는 아래 명령으로 만들고 작은따옴표로 감싼다(해시에 `$`가 들어 있다).

```bash
docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext '<팀 비밀번호>'
```

2. 로컬 DB를 덤프해 서버로 옮긴다.

```bash
docker exec capstone-be-catalog-db-1 pg_dump -U catalog -d catalog -Fc > catalog.dump
docker exec capstone-be-order-db-1 pg_dump -U orders -d orders -Fc > orders.dump
```

3. 서버에서 DB만 먼저 띄워 덤프를 복원한 뒤 나머지를 띄운다. 서비스가 먼저 뜨면 빈 DB에 마이그레이션을 적용해서 복원과 부딪힌다.

```bash
docker compose -f deploy/compose.yaml up -d --wait catalog-db order-db
docker compose -f deploy/compose.yaml exec -T catalog-db pg_restore -U catalog -d catalog --no-owner < catalog.dump
docker compose -f deploy/compose.yaml exec -T order-db pg_restore -U orders -d orders --no-owner < orders.dump
docker compose -f deploy/compose.yaml up -d --build
```

4. 확인한다. 팀 계정 없이 부르면 401이다.

```bash
curl -u team:<팀 비밀번호> 'https://<SITE_ADDRESS>/api/v1/products?category=104001&size=1'
```

처음 뜰 때 인증서를 받는다. 받았는지는 `docker compose -f deploy/compose.yaml logs caddy`의 `certificate obtained successfully`로 확인한다. 못 받으면 브라우저가 HTTPS 연결을 거부한다. 인증서는 `caddy-data` 볼륨에 남아 컨테이너를 다시 만들어도 다시 받지 않는다.

### FE 빌드

FE는 API와 같은 주소에서 Caddy가 정적 파일로 내준다(ADR-125). 파일은 FE 저장소의 배포 워크플로가 빌드해 서버 `/srv/peaupick-fe`에 복사하고, Caddy는 이 폴더를 읽기 전용으로 붙인다. 워크플로가 쓰는 키는 `fe-deploy` 계정으로 이 폴더에 파일을 쓰는 것만 된다(셸 접속, 읽기, 폴더 밖 쓰기는 거부). 올라간 커밋은 `/version.txt`로 확인한다.

서버를 새로 만들면 compose를 띄우기 전에 한 번 준비한다. 키를 새로 만들었으면 FE 저장소 시크릿 `DEPLOY_SSH_KEY`도 바꾼다.

```bash
sudo adduser --disabled-password --gecos '' --shell /bin/sh fe-deploy
sudo mkdir -p /srv/peaupick-fe /home/fe-deploy/.ssh
sudo chown fe-deploy:fe-deploy /srv/peaupick-fe
sudo chmod 755 /srv/peaupick-fe
echo 'restrict,command="/usr/bin/rrsync -wo /srv/peaupick-fe" <fe-deploy 공개 키>' | sudo tee /home/fe-deploy/.ssh/authorized_keys >/dev/null
sudo chown -R fe-deploy:fe-deploy /home/fe-deploy/.ssh
sudo chmod 700 /home/fe-deploy/.ssh
sudo chmod 600 /home/fe-deploy/.ssh/authorized_keys
```
