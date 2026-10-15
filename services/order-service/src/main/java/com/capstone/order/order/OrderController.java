package com.capstone.order.order;

import java.util.List;

import jakarta.validation.constraints.Max;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import com.capstone.order.order.OrderService.ItemInput;
import com.capstone.order.order.OrderService.OrderResult;

@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public OrderResult create(@Valid @RequestBody CreateOrderRequest request) {
        List<ItemInput> items = request.items().stream()
                .map(i -> new ItemInput(i.productId(), i.optionKey(), i.quantity()))
                .toList();
        return orderService.place(request.ordererKey(), items);
    }

    @ExceptionHandler(OrderFailedException.class)
    public ResponseEntity<OrderFailedResponse> orderFailed(OrderFailedException e) {
        HttpStatus status = e.getReason() == OrderFailedException.Reason.OPTION_NOT_FOUND
                ? HttpStatus.NOT_FOUND : HttpStatus.CONFLICT;
        return ResponseEntity.status(status).body(new OrderFailedResponse(
                e.getReason().name(),
                "주문할 수 없는 항목이 있습니다.",
                new FailedItem(e.getProductId(), e.getOptionKey(), e.getRequested(), e.getAvailable())));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_ORDER", "요청 형식이 올바르지 않습니다.");
    }

    public record CreateOrderRequest(
            @NotBlank @Size(max = 100) String ordererKey,
            @NotNull @Size(min = 1, max = 20) List<@Valid ItemRequest> items) {}

    public record ItemRequest(
            @NotNull Long productId,
            @NotNull @Size(max = 100) String optionKey,
            @NotNull @Positive @Max(99) Integer quantity) {}

    public record OrderFailedResponse(String code, String message, FailedItem failedItem) {}

    public record FailedItem(Long productId, String optionKey, int requested, int available) {}

    public record ErrorResponse(String code, String message) {}
}