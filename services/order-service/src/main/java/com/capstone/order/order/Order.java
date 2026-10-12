package com.capstone.order.order;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import jakarta.persistence.*;

import com.capstone.order.inventory.Inventory;

@Entity
@Table(name = "orders")
public class Order {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "orderer_key", nullable = false)
    private String ordererKey;

    @Column(name = "total_price", nullable = false)
    private int totalPrice;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<OrderItem> items = new ArrayList<>();

    protected Order() {}

    public Order(String ordererKey) {
        this.ordererKey = ordererKey;
        this.createdAt = Instant.now();
    }

    public void addItem(Inventory inventory, int quantity) {
        OrderItem item = new OrderItem(this, inventory, quantity);
        items.add(item);
        totalPrice += item.getUnitPrice() * quantity;
    }

    public Long getId() { return id; }
    public String getOrdererKey() { return ordererKey; }
    public int getTotalPrice() { return totalPrice; }
    public Instant getCreatedAt() { return createdAt; }
    public List<OrderItem> getItems() { return items; }
}
