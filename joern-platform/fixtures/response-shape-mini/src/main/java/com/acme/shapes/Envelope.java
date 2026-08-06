package com.acme.shapes;

/**
 * The wrapper TrainTicket puts around every payload — and the reason a
 * recovered shape used to stop one field short of the answer.
 *
 * `data` is a type PARAMETER. Services declare the methods that build this as
 * a RAW `Envelope`, so no signature anywhere names what `T` is; only the
 * return statement that constructs it does.
 */
public class Envelope<T> {

    /**
     * A static field the generated constructor never takes. The binding maps
     * field POSITION onto argument position, so counting this one skipped the
     * binding entirely (arity mismatch) and would have shifted every index
     * after it had the count happened to match.
     */
    private static final String KIND = "envelope";

    private Integer status;

    private String msg;

    private T data;

    public Envelope(Integer status, String msg, T data) {
        this.status = status;
        this.msg = msg;
        this.data = data;
    }

    public Integer getStatus() {
        return status;
    }

    public String getMsg() {
        return msg;
    }

    public T getData() {
        return data;
    }
}
