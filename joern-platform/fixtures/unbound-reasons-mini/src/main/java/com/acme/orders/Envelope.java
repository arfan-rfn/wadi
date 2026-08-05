package com.acme.orders;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * The shape that made 585 train-ticket-aitest calls read as a binding failure.
 *
 * Every constructor here is Lombok-generated. javasrc2cpg materializes exactly
 * ONE bodiless `<init>:void()` stub, while call sites use the 3-arg
 * `@AllArgsConstructor` form that has no declaration at all. Matching a
 * declaration by NAME let that stub stand in for the constructor actually
 * being called, so the classifier reported "the type declares this and the
 * call still did not bind" about a method that was never in the source.
 */
@Data
@AllArgsConstructor
@NoArgsConstructor
public class Envelope {

    private Integer status;

    private String msg;

    private Object data;
}
