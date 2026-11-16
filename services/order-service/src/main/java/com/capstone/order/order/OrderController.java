package com.capstone.order.order;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import jakarta.validation.constraints.Max;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import com.capstone.order.order.OrderService.ItemInput;
import com.capstone.order.order.OrderService.ItemKey;
import com.capstone.order.order.OrderService.OrderResult;

@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {

    static final int MAX_QUANTITY = 99;

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public OrderResult create(@Valid @RequestBody CreateOrderRequest request) {
        if (exceedsMaxQuantity(request.items())) {
            throw new InvalidOrderException();
        }
        List<ItemInput> items = request.items().stream()
                .map(i -> new ItemInput(i.productId(), i.optionKey(), i.quantity()))
                .toList();
        return orderService.place(request.ordererKey(), request.requestId(), items);
    }

    @ExceptionHandler(OrderFailedException.class)
    public ResponseEntity<OrderFailedResponse> orderFailed(OrderFailedException e) {
        HttpStatus status = switch (e.getReason()) {
            case OPTION_NOT_FOUND -> HttpStatus.NOT_FOUND;
            case LOCK_TIMEOUT, LOCK_UNAVAILABLE -> HttpStatus.SERVICE_UNAVAILABLE;
            default -> HttpStatus.CONFLICT;
        };
        return ResponseEntity.status(status).body(new OrderFailedResponse(
                e.getReason().name(),
                "주문할 수 없는 항목이 있습니다.",
                new FailedItem(e.getProductId(), e.getOptionKey(), e.getRequested(), e.getAvailable()),
                e.getSoldOutItems()));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class,
            InvalidOrderException.class})
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_ORDER", "요청 형식이 올바르지 않습니다.");
    }

    /** Lines for the same option are merged into one order item, so their total must stay within the limit too. */
    private static boolean exceedsMaxQuantity(List<ItemRequest> items) {
        Map<ItemKey, Integer> totals = new HashMap<>();
        for (ItemRequest item : items) {
            int total = totals.merge(new ItemKey(item.productId(), item.optionKey()), item.quantity(), Integer::sum);
            if (total > MAX_QUANTITY) {
                return true;
            }
        }
        return false;
    }

    public record CreateOrderRequest(
            @NotBlank @Size(max = 100) String ordererKey,
            @Size(min = 1, max = 100) String requestId,
            @NotNull @Size(min = 1, max = 20) List<@NotNull @Valid ItemRequest> items) {}

    public record ItemRequest(
            @NotNull Long productId,
            @NotNull @Size(max = 100) String optionKey,
            @NotNull @Positive @Max(MAX_QUANTITY) Integer quantity) {}

    public record OrderFailedResponse(String code, String message, FailedItem failedItem,
                                      List<SoldOutItem> soldOutItems) {}

    public record FailedItem(Long productId, String optionKey, int requested, int available) {}

    public record ErrorResponse(String code, String message) {}

    static class InvalidOrderException extends RuntimeException {
        InvalidOrderException() {
            super("INVALID_ORDER");
        }
    }
}
