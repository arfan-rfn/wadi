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
