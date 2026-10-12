package com.capstone.order.order;

import jakarta.persistence.*;

import com.capstone.order.inventory.Inventory;

@Entity
@Table(name = "order_items")
public class OrderItem {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "order_id")
    private Order order;

    @Column(name = "product_id", nullable = false)
    private Long productId;

    @Column(name = "option_key", nullable = false)
    private String optionKey;

    @Column(nullable = false)
    private String name;

    @Column(name = "unit_price", nullable = false)
    private int unitPrice;

    @Column(nullable = false)
    private int quantity;

    protected OrderItem() {}

    OrderItem(Order order, Inventory inventory, int quantity) {
        this.order = order;
        this.productId = inventory.getProductId();
        this.optionKey = inventory.getOptionKey();
        this.name = inventory.getName();
        this.unitPrice = inventory.getPrice();
        this.quantity = quantity;
    }

    public Long getProductId() { return productId; }
    public String getOptionKey() { return optionKey; }
    public String getName() { return name; }
    public int getUnitPrice() { return unitPrice; }
    public int getQuantity() { return quantity; }
}