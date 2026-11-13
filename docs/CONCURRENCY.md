# 재고 동시성 실험 결과 (8~10주차)

한 옵션에 주문이 몰릴 때 재고 차감 방식 다섯 가지를 같은 시나리오로 비교한 결과다. 방식은 `order.stock-strategy`로 고른다. 결정과 근거는 Notion ADR에 남긴다.

## 1. 요약

| 방식 | 초과 판매 | 성공 처리량 (재고 충분) | p95 (재고 충분) | 특이점 |
|---|---|---|---|---|
| `none` | **발생** (재고 50에 200건 판매) | 1616 | 44ms | 재고 1000개를 팔고도 107개만 줄어듦 (갱신 손실) |
| `conditional` (기본값) | 0 | 721 | 91ms | 쿼리 한 번으로 확인과 차감 |
| `pessimistic` | 0 | 718 | 82ms | `conditional`과 거의 같음 |
| `optimistic` | 0 | 319 | 56ms | 재고가 남아도 71%가 충돌로 실패 |
| `redisson` | 0 | 389 | 195ms | 가장 느림. Redis가 멈추면 주문을 모두 거절(503)하지만 거절에 26초 걸림 |

- 락이 있는 네 방식은 모두 초과 판매가 0건이다.
- 서버가 한 대인 지금은 `conditional`과 `pessimistic`이 정확성과 처리량을 함께 만족한다.
- `optimistic`은 재시도 없이 한 옵션에 경쟁이 몰리는 상황에 맞지 않는다.
- `redisson`은 서버를 여러 대로 늘려 DB 밖에서 순서를 정해야 할 때 의미가 있다. 지금은 Redis 왕복만큼 느리고, Redis 장애 때 응답이 오래 걸리는 문제가 남아 있다.

## 2. 방식

| `order.stock-strategy` | 방법 | 클래스 |
|---|---|---|
| `none` | 읽고, 비교하고, 엔티티 값을 바꿔 저장한다. 락 없음. 기준선이다 | `NoLockStockDecreaser` |
| `conditional` | `UPDATE ... WHERE quantity >= :qty` 한 번으로 확인과 차감을 같이 한다 | `ConditionalUpdateStockDecreaser` |
| `pessimistic` | `SELECT ... FOR UPDATE`로 행을 잠그고 읽은 뒤 차감한다 | `PessimisticLockStockDecreaser` |
| `optimistic` | 락 없이 읽고, 읽은 버전이 그대로일 때만 차감한다. 충돌하면 재시도 없이 실패한다 | `OptimisticLockStockDecreaser` |
| `redisson` | Redis 분산 락(`stock:상품ID:옵션키`)을 잡고 읽은 뒤 차감한다. 락은 커밋 뒤에 푼다 | `RedissonLockStockDecreaser` |

- `optimistic`은 JPA `@Version` 대신 버전 컬럼을 쿼리에서 직접 비교한다. `@Version`을 쓰면 `none`의 UPDATE에도 버전 검사가 붙어 기준선이 사라진다.
- `redisson`은 DB 쪽 보호 없이 `none`과 같은 확인·차감 코드를 쓴다. Redis 락만으로 막는지 보기 위해서다. 차감 직후에 락을 풀면 다음 주문이 커밋 전 재고를 읽으므로, 트랜잭션이 끝난 뒤 푼다.
- 주문 항목은 (상품 ID, 옵션 키) 순으로 정렬해 처리한다. 여러 옵션을 담은 주문끼리 서로 기다리는 교착을 막는다.

## 3. 정확성: 재현 테스트

테스트: `OversellReproductionTest`

- 재고 1개인 옵션 하나에 1개씩 주문 5건을 동시에 보낸다.
- 경쟁 구간이 매번 같도록 출발선(`CyclicBarrier`)에서 5건을 모았다가 동시에 진행시킨다. `none`·`optimistic`은 재고 확인 뒤, `pessimistic`·`redisson`은 락 요청 직전에 모은다. 락을 잡은 채 기다리면 나머지가 락에 막혀 모이지 못하기 때문이다.

| 방식 | 성공 | 실패 (사유) | 초과 판매 | 최종 재고 |
|---|---|---|---|---|
| `none` | 5 | 0 | 4 | 0 |
| `pessimistic` | 1 | 4 (`OUT_OF_STOCK`) | 0 | 0 |
| `optimistic` | 1 | 4 (`OUT_OF_STOCK`) | 0 | 0 |
| `redisson` | 1 | 4 (`OUT_OF_STOCK`) | 0 | 0 |

- `none`: 5건이 모두 "재고 1 ≥ 주문 1"을 통과한 뒤 각자 `quantity = 0`을 저장했다. 뒤 주문이 앞 주문의 차감을 덮어써서, 5개가 팔렸는데 재고는 1개만 줄었다.
- `pessimistic`, `redisson`: 확인과 차감 사이에 다른 주문이 끼어들지 못해, 뒤 주문들은 차감된 재고(0)를 보고 품절로 끝났다.
- `optimistic`: 5건 모두 확인을 통과했지만 버전이 바뀌지 않은 1건만 차감에 성공했다. 나머지는 재고를 다시 읽어 품절로 응답했다.
- `conditional`은 `OrderConcurrencyTest`(재고 5개에 10건 동시 주문 → 정확히 5건 성공)로 확인한다.

## 4. 성능: 부하 측정

### 조건

- 실행 중인 order-service에 `scripts/bench_orders.py`로 주문을 보낸다. 모든 요청이 같은 옵션 하나를 1개씩 주문해 한 행에 경쟁이 몰린다.
- 동시 요청 50개(파이썬 스레드), 서버 DB 연결 풀 10개(HikariCP 기본값). 본 측정 전에 다른 상품으로 200건 워밍업한다.
- 로컬 Mac 한 대에서 클라이언트·서버·PostgreSQL·Redis(Docker)를 같이 돌렸다. 절대 수치보다 방식 사이의 차이를 본다.
- `none`, `conditional`은 9주차에, `pessimistic`, `optimistic`, `redisson`은 10주차에 같은 날 쟀다. 두 번 잰 `pessimistic`(737 → 718)과 `optimistic`(311 → 319)의 성공 처리량은 3% 안쪽으로 차이가 났다.
- 방식마다 시나리오별로 한 번씩 쟀다.
- 성공 처리량 = 성공 수 ÷ 전체 소요 시간. 실패 응답은 빨리 끝나서 전체 TPS를 부풀리므로 따로 계산했다.
- 재고 오차 = 남은 재고 − (처음 재고 − 생성된 주문 수). 0이 아니면 갱신 손실이다.

### 재고 충분 (재고 1000, 요청 1000)

| 방식 | 측정 | TPS | 성공 처리량 | p50 (ms) | p95 (ms) | 성공 | 실패 (사유) | 초과 판매 | 재고 오차 |
|---|---|---|---|---|---|---|---|---|---|
| `none` | 9주차 | 1616 | 1616 | 29 | 44 | 1000 | 0 | 0 | 893 |
| `conditional` | 9주차 | 721 | 721 | 65 | 91 | 1000 | 0 | 0 | 0 |
| `pessimistic` | 10주차 | 718 | 718 | 66 | 82 | 1000 | 0 | 0 | 0 |
| `optimistic` | 10주차 | 1099 | 319 | 46 | 56 | 290 | `CONCURRENT_UPDATE` 710 | 0 | 0 |
| `redisson` | 10주차 | 389 | 389 | 117 | 195 | 1000 | 0 (`LOCK_TIMEOUT` 0) | 0 | 0 |

### 재고 부족 (재고 50, 요청 200)

| 방식 | 측정 | TPS | p50 (ms) | p95 (ms) | 성공 | 실패 (사유) | 초과 판매 | 재고 오차 |
|---|---|---|---|---|---|---|---|---|
| `none` | 9주차 | 1838 | 24 | 30 | 200 | 0 | 150 | 30 |
| `conditional` | 9주차 | 1920 | 15 | 59 | 50 | `OUT_OF_STOCK` 150 | 0 | 0 |
| `pessimistic` | 10주차 | 1716 | 17 | 57 | 50 | `OUT_OF_STOCK` 150 | 0 | 0 |
| `optimistic` | 10주차 | 1295 | 38 | 51 | 50 | `CONCURRENT_UPDATE` 115, `OUT_OF_STOCK` 35 | 0 | 0 |
| `redisson` | 10주차 | 638 | 61 | 122 | 50 | `OUT_OF_STOCK` 150 (`LOCK_TIMEOUT` 0) | 0 | 0 |

## 5. Redis 장애 (`redisson`)

`redisson`으로 띄운 order-service는 그대로 두고 Redis 컨테이너만 멈췄다가 다시 켰다. 재고 50, 요청 200, 워밍업 없음.

| 상황 | TPS | p50 (ms) | p95 (ms) | 성공 | 실패 (사유) | 초과 판매 | 재고 오차 |
|---|---|---|---|---|---|---|---|
| Redis 중단 | 2 | 26096 | 27439 | 0 | `LOCK_UNAVAILABLE` 200 | 0 | 0 |
| Redis 재시작 후 (서비스 재시작 없음) | 615 | 66 | 117 | 50 | `OUT_OF_STOCK` 150 | 0 | 0 |

- Redis가 없는 상태로 `redisson`을 고르고 order-service를 시작하면 약 6.6초 뒤 `RedisConnectionException: Unable to connect to Redis server`로 기동에 실패한다.
- 락 실패는 503으로 응답한다. 대기 시간(`order.redisson.wait-millis`, 3초)을 넘기면 `LOCK_TIMEOUT`, Redis에 연결하지 못하면 `LOCK_UNAVAILABLE`이다.

## 6. 해석

- `none`은 가장 빠르지만 틀린다. 재고 충분에서 1000개를 팔고도 재고가 107개만 줄었고(재고 오차 893), 재고 부족에서는 50개 재고로 200건을 팔았다.
- `conditional`과 `pessimistic`은 초과 판매와 재고 오차가 0이고 성공 처리량이 비슷하다(721, 718). 둘 다 같은 행을 한 번에 하나씩 고치기 때문이다.
- `optimistic`도 초과 판매는 0이지만 한 행에 경쟁이 몰리면 대부분 충돌한다. 재고가 충분한데도 1000건 중 710건이 `CONCURRENT_UPDATE`로 실패해 성공 처리량이 319다. 재고 부족에서 실패가 대부분 `CONCURRENT_UPDATE`인 것은 충돌한 시점에는 재고가 남아 있었기 때문이다.
- `redisson`은 성공 처리량이 389로 `pessimistic`의 절반 정도다. 주문마다 Redis에 락을 잡고 푸는 왕복이 더해지고, 커밋이 끝날 때까지 락을 쥔다.
- Redis가 멈추면 `redisson`은 주문을 모두 거절해 초과 판매를 막았다. DB 락으로 넘어가지 않도록 일부러 거절하게 했다. 대신 거절하는 데 26초가 걸렸다. Redisson 4.7.0의 기본 재시도(`retryAttempts` 4번, 재시도 사이 대기)로 락 시도 한 번이 1초 타임아웃보다 길어지고, DB 트랜잭션을 연 뒤 락을 기다려서 그동안 DB 연결(10개)을 쥐기 때문으로 본다. 재시도 시간은 기본값으로 계산한 것이고 직접 재지는 않았다.

## 7. 남은 과제

- `redisson`의 락을 트랜잭션 밖에서 먼저 잡고, 락 획득 재시도를 줄인다(`retryAttempts` 0~1). 바꾼 뒤 5장의 "Redis 중단"을 같은 조건으로 다시 재서 나란히 적는다.
- 방식마다 한 번씩만 쟀다. `conditional`과 `pessimistic`처럼 차이가 작은 비교는 반복 측정이 필요하다.
- Gateway를 거쳐도 초과 판매가 0인지 다시 확인한다.

## 8. 재현 방법

정확성 테스트:

```bash
./gradlew :services:order-service:test --tests "*OversellReproductionTest" -i | grep "\[oversell\]"
```

부하 측정은 터미널 두 개를 쓴다. 측정 전에 떠 있는 서비스의 방식이 하나뿐인지 확인한다.

```bash
make infra-up
./gradlew :services:order-service:bootRun --args='--order.stock-strategy=pessimistic'   # 터미널 1
ps -ef | grep -o "order.stock-strategy=[a-z]*" | sort -u                                # 터미널 2
uv run python scripts/bench_orders.py --strategy pessimistic --stock 1000 --requests 1000
uv run python scripts/bench_orders.py --strategy pessimistic --stock 50 --requests 200
```

Redis 장애는 `redisson`으로 띄운 채 다음을 돌린다. 로컬에 다른 Redis가 6379를 쓰고 있으면 먼저 끈다.

```bash
docker compose stop redis
uv run python scripts/bench_orders.py --strategy redisson-redis-down --stock 50 --requests 200 --warmup 0
docker compose start redis
sleep 5
uv run python scripts/bench_orders.py --strategy redisson-recovered --stock 50 --requests 200 --warmup 0
```
