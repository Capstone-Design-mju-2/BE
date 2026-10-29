package com.capstone.order.order;

import java.util.concurrent.TimeUnit;

import org.redisson.Redisson;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.redisson.config.Config;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;

public class RedissonLockStockDecreaser implements StockDecreaser, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(RedissonLockStockDecreaser.class);

    private final InventoryRepository inventoryRepository;
    private final RedissonClient redisson;
    private final long waitMillis;
    private final Runnable beforeLock;

    public RedissonLockStockDecreaser(InventoryRepository inventoryRepository, RedissonClient redisson,
                                      long waitMillis) {
        this(inventoryRepository, redisson, waitMillis, () -> {});
    }

    RedissonLockStockDecreaser(InventoryRepository inventoryRepository, RedissonClient redisson,
                               long waitMillis, Runnable beforeLock) {
        this.inventoryRepository = inventoryRepository;
        this.redisson = redisson;
        this.waitMillis = waitMillis;
        this.beforeLock = beforeLock;
    }

    static RedissonClient connect(String address, int timeoutMillis) {
        Config config = new Config();
        config.useSingleServer()
                .setAddress(address)
                .setConnectTimeout(timeoutMillis)
                .setTimeout(timeoutMillis);
        return Redisson.create(config);
    }

    @Override
    public Inventory decrease(Long productId, String optionKey, int quantity) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            throw new IllegalStateException("Redisson 락은 트랜잭션 안에서만 쓸 수 있습니다");
        }
        beforeLock.run();
        String key = "stock:" + productId + ":" + optionKey;
        RLock lock = redisson.getLock(key);
        boolean acquired;
        try {
            acquired = lock.tryLock(waitMillis, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw OrderFailedException.lockTimeout(productId, optionKey, quantity);
        } catch (RuntimeException e) {
            log.warn("Redis 락을 얻지 못했습니다: {}", key, e);
            throw OrderFailedException.lockUnavailable(productId, optionKey, quantity);
        }
        if (!acquired) {
            throw OrderFailedException.lockTimeout(productId, optionKey, quantity);
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCompletion(int status) {
                unlock(lock, key);
            }
        });

        Inventory inventory = inventoryRepository.findByProductIdAndOptionKey(productId, optionKey)
                .orElseThrow(() -> OrderFailedException.notFound(productId, optionKey, quantity));
        if (inventory.getQuantity() < quantity) {
            throw OrderFailedException.shortage(inventory, quantity);
        }
        inventory.decrease(quantity);
        return inventory;
    }

    private static void unlock(RLock lock, String key) {
        try {
            if (lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        } catch (RuntimeException e) {
            log.warn("Redis 락을 풀지 못했습니다: {}", key, e);
        }
    }

    @Override
    public void close() {
        redisson.shutdown();
    }
}