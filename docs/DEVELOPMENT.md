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

MCP 서버는 stdio transport를 사용한다.

```bash
make run-search-mcp
make run-inventory-mcp
```

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
